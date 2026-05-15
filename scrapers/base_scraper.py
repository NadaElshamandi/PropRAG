"""
base_scraper.py
---------------
Shared base class for all property scrapers.
Handles: DB client, deduplication, logging, retry logic.
"""

import os
import time
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional

from pathlib import Path
from dotenv import load_dotenv
from playwright.async_api import async_playwright, Browser, BrowserContext

from scrapers.db import DBClient

load_dotenv(Path(__file__).parent / ".env")

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
        self.db = DBClient()
        self.source_id: Optional[str] = None
        self.scrape_log_id: Optional[str] = None

        self.stats = {
            "listings_found": 0,
            "new_listings": 0,
            "duplicates_skipped": 0,
        }

    # ── Source / scrape-log helpers (via DBClient) ───────────────────────────

    def _get_source_id(self) -> str:
        return self.db.get_source_id(self.source_name)

    def _start_scrape_log(self) -> str:
        res = (
            self.db.supabase.table("scrape_logs")
            .insert({"source_id": self.source_id, "status": "partial"})
            .execute()
        )
        return res.data[0]["id"]

    def _finish_scrape_log(self, status: str = "success", error: str = None):
        payload = {
            **self.stats,
            "status": status,
            "error_message": error,
        }
        self.db.supabase.table("scrape_logs").update(payload).eq(
            "id", self.scrape_log_id
        ).execute()

    def _update_source_last_scraped(self):
        self.db.supabase.table("sources").update(
            {"last_scraped_at": datetime.now(timezone.utc).isoformat()}
        ).eq("id", self.source_id).execute()

    def _listing_exists(self, external_id: str) -> bool:
        res = (
            self.db.supabase.table("listings")
            .select("id")
            .eq("source_id", self.source_id)
            .eq("external_id", external_id)
            .execute()
        )
        return len(res.data) > 0

    def _upsert_listing(self, data: dict) -> Optional[str]:
        """
        Delegate to DBClient.
        Tracks new vs duplicate for scrape_log stats.
        """
        listing_id, is_new = self.db.upsert_listing(self.source_id, data)
        if listing_id is None:
            return None
        if is_new:
            self.stats["new_listings"] += 1
        else:
            self.stats["duplicates_skipped"] += 1
        return listing_id

    # ── Browser helpers ──────────────────────────────────────────────────────

    async def _make_browser(self, playwright) -> tuple[Browser, BrowserContext]:
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
        await context.route(
            "**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf}",
            lambda route: route.abort(),
        )
        return browser, context

    @staticmethod
    def _clean_price(raw: str) -> Optional[int]:
        if not raw:
            return None
        digits = "".join(c for c in raw if c.isdigit())
        return int(digits) if digits else None

    @staticmethod
    def _clean_area(raw: str) -> Optional[float]:
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
            self.db.supabase.table("scrape_logs").update(
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
