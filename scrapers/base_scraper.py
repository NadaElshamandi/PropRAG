"""
base_scraper.py
---------------
Shared base class for all property scrapers.
Handles: Supabase connection, deduplication, logging, retry logic.
"""

import os
import time
import logging
import hashlib
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv
from supabase import create_client, Client
from playwright.async_api import async_playwright, Browser, BrowserContext

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


class BaseScraper(ABC):
    """
    Abstract base class every source scraper inherits from.

    Subclasses must implement:
        - source_name: str
        - search_url(page: int) -> str
        - parse_listing_card(card) -> dict | None
        - parse_listing_detail(page, url) -> dict
    """

    source_name: str = ""

    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.supabase: Client = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_SERVICE_KEY"],
        )
        self.source_id: Optional[str] = None
        self.scrape_log_id: Optional[str] = None

        # Stats for the current run
        self.stats = {
            "listings_found": 0,
            "new_listings": 0,
            "duplicates_skipped": 0,
        }

    # ── Supabase helpers ─────────────────────────────────────────────────────

    def _get_source_id(self) -> str:
        """Fetch this scraper's source UUID from the DB."""
        res = (
            self.supabase.table("sources")
            .select("id")
            .eq("name", self.source_name)
            .single()
            .execute()
        )
        return res.data["id"]

    def _start_scrape_log(self) -> str:
        """Insert a scrape_log row and return its ID."""
        res = (
            self.supabase.table("scrape_logs")
            .insert({"source_id": self.source_id, "status": "partial"})
            .execute()
        )
        return res.data[0]["id"]

    def _finish_scrape_log(self, status: str = "success", error: str = None):
        """Update the scrape_log row with final stats."""
        payload = {
            **self.stats,
            "status": status,
            "error_message": error,
        }
        self.supabase.table("scrape_logs").update(payload).eq(
            "id", self.scrape_log_id
        ).execute()

    def _update_source_last_scraped(self):
        self.supabase.table("sources").update(
            {"last_scraped_at": datetime.now(timezone.utc).isoformat()}
        ).eq("id", self.source_id).execute()

    def _listing_exists(self, external_id: str) -> bool:
        """Check if a listing from this source already exists."""
        res = (
            self.supabase.table("listings")
            .select("id")
            .eq("source_id", self.source_id)
            .eq("external_id", external_id)
            .execute()
        )
        return len(res.data) > 0

    def _upsert_listing(self, data: dict) -> Optional[str]:
        """
        Insert a new listing or update last_seen_at if it already exists.
        Returns the listing UUID.
        """
        external_id = data.get("external_id")

        # Check for duplicate
        existing = (
            self.supabase.table("listings")
            .select("id")
            .eq("source_id", self.source_id)
            .eq("external_id", external_id)
            .execute()
        )

        if existing.data:
            # Update last_seen_at so we know it's still live
            listing_id = existing.data[0]["id"]
            self.supabase.table("listings").update(
                {"last_seen_at": datetime.now(timezone.utc).isoformat()}
            ).eq("id", listing_id).execute()
            self.stats["duplicates_skipped"] += 1
            return listing_id

        # New listing — insert
        listing_payload = {k: v for k, v in data.items()
                           if k not in ("location", "contacts", "media")}
        listing_payload["source_id"] = self.source_id

        res = self.supabase.table("listings").insert(listing_payload).execute()
        listing_id = res.data[0]["id"]
        self.stats["new_listings"] += 1

        # Insert related rows
        if data.get("location"):
            self.supabase.table("locations").insert(
                {"listing_id": listing_id, **data["location"]}
            ).execute()

        for contact in data.get("contacts", []):
            self.supabase.table("contacts").insert(
                {"listing_id": listing_id, **contact}
            ).execute()

        for i, url in enumerate(data.get("media", [])):
            self.supabase.table("media").insert(
                {"listing_id": listing_id, "url": url, "sort_order": i}
            ).execute()

        self.logger.info(f"  ✓ Saved new listing: {data.get('title', '')[:60]}")
        return listing_id

    # ── Browser helpers ──────────────────────────────────────────────────────

    async def _make_browser(self, playwright) -> tuple[Browser, BrowserContext]:
        """Launch a stealth-ish browser context."""
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            viewport={"width": 1280, "height": 900},
        )
        # Block images and fonts to speed up scraping
        await context.route(
            "**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf}",
            lambda route: route.abort(),
        )
        return browser, context

    @staticmethod
    def _clean_price(raw: str) -> Optional[int]:
        """Extract integer EGP price from strings like 'EGP 5,500,000'."""
        if not raw:
            return None
        digits = "".join(c for c in raw if c.isdigit())
        return int(digits) if digits else None

    @staticmethod
    def _clean_area(raw: str) -> Optional[float]:
        """Extract float sqm from strings like '161 sqm'."""
        if not raw:
            return None
        digits = "".join(c for c in raw if c.isdigit() or c == ".")
        return float(digits) if digits else None

    @staticmethod
    def _clean_int(raw: str) -> Optional[int]:
        if not raw:
            return None
        digits = "".join(c for c in raw if c.isdigit())
        return int(digits) if digits else None

    # ── Abstract interface ───────────────────────────────────────────────────

    @abstractmethod
    async def scrape(self):
        """Entry point — called by the scheduler."""
        ...

    # ── Main run ─────────────────────────────────────────────────────────────

    async def run(self):
        """Orchestrates the full scrape run with logging and error handling."""
        self.source_id = self._get_source_id()
        self.scrape_log_id = self._start_scrape_log()
        start = time.time()

        try:
            self.logger.info(f"Starting scrape: {self.source_name}")
            await self.scrape()
            duration = round(time.time() - start, 1)
            self.supabase.table("scrape_logs").update(
                {"duration_seconds": duration}
            ).eq("id", self.scrape_log_id).execute()
            self._finish_scrape_log(status="success")
            self._update_source_last_scraped()
            self.logger.info(
                f"Done. Found={self.stats['listings_found']} "
                f"New={self.stats['new_listings']} "
                f"Dupes={self.stats['duplicates_skipped']} "
                f"Time={duration}s"
            )
        except Exception as e:
            self.logger.error(f"Scrape failed: {e}", exc_info=True)
            self._finish_scrape_log(status="failed", error=str(e))
            raise
