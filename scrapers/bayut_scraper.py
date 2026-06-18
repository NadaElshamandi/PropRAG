"""
bayut_scraper.py
----------------
Scraper for Bayut.eg using Algolia API interception.

Bayut uses Algolia search backend. The API key is browser-restricted,
so we use Playwright to intercept the Algolia responses in-flight.

Usage:
    uv run python -m scrapers.bayut_scraper
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from playwright.async_api import Browser, BrowserContext, Page

from scrapers.base_scraper import BaseScraper
from scrapers.neighborhoods import normalize_district

logger = logging.getLogger("BayutScraper")


class BayutAPIScraper(BaseScraper):
    """
    Scraper for Bayut.eg listings via Algolia API interception.
    """

    source_name: str = "bayut"

    # Bayut search URL for Alexandria apartments for sale
    BASE_URL = "https://www.bayut.eg/en/alexandria/apartments-for-sale/"

    async def scrape(self):
        """
        Main entry point. Navigate Bayut, intercept Algolia responses,
        extract listings, and upsert to DB.
        """
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser, context = await self._make_browser(p)
            page = await context.new_page()

            # Store intercepted listings here
            listings_data: list[dict] = []

            # Intercept Algolia responses
            page.on(
                "response",
                lambda resp: asyncio.create_task(
                    self._intercept_algolia(resp, listings_data)
                ),
            )

            try:
                logger.info("Navigating to Bayut Alexandria apartments page...")
                # Use domcontentloaded to avoid timeout on heavy pages
                await page.goto(self.BASE_URL, wait_until="domcontentloaded", timeout=60000)
                # Wait longer for Algolia API calls to fire
                await page.wait_for_timeout(10000)

                # Scroll to trigger more Algolia calls if using infinite scroll
                logger.info("Scrolling to load more listings...")
                for _ in range(3):
                    await page.evaluate("window.scrollBy(0, 800)")
                    await page.wait_for_timeout(3000)

                # Wait a bit more for any delayed requests
                await page.wait_for_timeout(5000)

                logger.info(f"Intercepted {len(listings_data)} raw listing entries")

                # Process and upsert
                processed_ids = set()
                for raw in listings_data:
                    external_id = str(raw.get("id", ""))
                    if not external_id or external_id in processed_ids:
                        continue
                    processed_ids.add(external_id)

                    parsed = self._parse_listing(raw)
                    if parsed:
                        self.stats["listings_found"] += 1
                        self._upsert_listing(parsed)

            finally:
                await browser.close()

    async def _intercept_algolia(
        self, response, listings_data: list[dict]
    ):
        """
        Playwright response handler. If the response is from Algolia
        and contains listing hits, append them to listings_data.
        """
        try:
            url = response.url
            if "algolia" not in url.lower():
                return

            content_type = response.headers.get("content-type", "")
            if "json" not in content_type.lower():
                return

            body = await response.text()
            if len(body) < 1000:  # Skip tiny responses (likely empty or config)
                return

            data = json.loads(body)
            if not isinstance(data, dict) or "results" not in data:
                return

            # Algolia returns {"results": [{"hits": [...]}]}
            for result in data["results"]:
                hits = result.get("hits", [])
                if hits and isinstance(hits, list):
                    # Filter for actual property listings (not agents, not empty)
                    for hit in hits:
                        if hit.get("purpose") == "for-sale" or hit.get("price"):
                            listings_data.append(hit)

        except Exception:
            # Silently ignore parsing errors for non-listing responses
            pass

    def _parse_listing(self, raw: dict) -> Optional[dict[str, Any]]:
        """
        Map a raw Bayut Algolia hit to our DB schema.
        """
        try:
            external_id = str(raw.get("id", ""))
            if not external_id:
                return None

            # Price is already numeric in Algolia
            price = raw.get("price")
            if isinstance(price, float):
                price = int(price)

            # Area
            area = raw.get("area")
            if isinstance(area, str):
                area = self._clean_area(area)
            elif isinstance(area, (int, float)):
                area = float(area)

            # Bedrooms / Bathrooms
            rooms = raw.get("rooms", 0)
            baths = raw.get("baths", 0)
            if isinstance(rooms, str):
                rooms = self._clean_int(rooms) or 0
            if isinstance(baths, str):
                baths = self._clean_int(baths) or 0

            # Location
            geo = raw.get("geography", {})
            lat = geo.get("lat")
            lng = geo.get("lng")

            # Title (English) and title_l1 (Arabic)
            title = raw.get("title", "")
            title_ar = raw.get("title_l1", "")

            # Reference number as listing_url fallback
            ref = raw.get("referenceNumber", "")
            slug = raw.get("slug", "")
            
            # Build listing URL
            listing_url = None
            if slug:
                listing_url = f"https://www.bayut.eg/en/property/{slug}/"
            elif ref:
                listing_url = f"https://www.bayut.eg/en/property/{ref}/"

            # Photo URLs
            photos = raw.get("photoList", [])
            media_urls = [p.get("url", "") for p in photos if p.get("url")]

            # Build composite description from available fields
            description_parts = []
            if title:
                description_parts.append(title)
            if raw.get("amenities"):
                description_parts.append(
                    f"Amenities: {', '.join(raw['amenities'])}"
                )
            if raw.get("description"):
                description_parts.append(raw["description"])

            description = "\n".join(description_parts) if description_parts else title

            # District extraction from location array
            # Bayut location: [{level:0, name:'Egypt'}, {level:1, name:'Alexandria'}, {level:2, name:'District'}]
            district = None
            neighborhood = None
            location_name = ""
            
            location_array = raw.get("location", [])
            if isinstance(location_array, list):
                for loc in location_array:
                    if isinstance(loc, dict):
                        level = loc.get("level")
                        name = loc.get("name", "")
                        if level == 1:
                            location_name = name  # Province/city
                        elif level == 2:
                            district = normalize_district(name) or name
                            neighborhood = name
            
            # Fallback: if no district extracted, try to normalize from title
            if not district and title:
                # Try to find district name in title
                from scrapers.neighborhoods import DISTRICT_ALIASES
                for canonical, aliases in DISTRICT_ALIASES.items():
                    for alias in aliases:
                        if alias.lower() in title.lower():
                            district = canonical
                            break
                    if district:
                        break

            return {
                "external_id": external_id,
                "listing_url": listing_url,
                "title": title,
                "description": description,
                "price_egp": price,
                "area_sqm": area,
                "bedrooms": rooms if rooms > 0 else None,
                "bathrooms": baths if baths > 0 else None,
                "location": {
                    "district": district or neighborhood or "Alexandria",
                    "neighborhood": neighborhood or "",
                    "latitude": lat,
                    "longitude": lng,
                    "raw_address": location_name,
                },
                "contacts": [],  # Bayut Algolia doesn't expose contact info
                "media": media_urls,
                "status": "active",
            }

        except Exception as e:
            logger.warning(f"Failed to parse listing: {e}")
            return None


if __name__ == "__main__":
    scraper = BayutAPIScraper()
    asyncio.run(scraper.run())
