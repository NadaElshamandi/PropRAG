"""
bayut_scraper.py
----------------
Enhanced scraper for Bayut.eg using Algolia API interception.

Features:
- Pagination support (scroll to load more)
- District-specific scraping
- Filter by price, bedrooms
- Batch processing with error recovery

Usage:
    uv run python -m scrapers.bayut_scraper
    uv run python -m scrapers.bayut_scraper --district Smouha
    uv run python -m scrapers.bayut_scraper --max-pages 5
"""

import argparse
import asyncio
import json
import logging
from typing import Any, Optional

from playwright.async_api import Browser, BrowserContext, Page

from scrapers.base_scraper import BaseScraper
from scrapers.neighborhoods import _ALEXANDRIA_DISTRICTS as DISTRICT_ALIASES, normalize_district

logger = logging.getLogger("BayutScraper")


class BayutAPIScraper(BaseScraper):
    """
    Scraper for Bayut.eg listings via Algolia API interception.
    
    Can scrape:
    - All Alexandria apartments (default)
    - Specific districts
    - Multiple pages with pagination
    """

    source_name: str = "bayut"

    # Base URL patterns
    BASE_URL = "https://www.bayut.eg/en/alexandria/apartments-for-sale/"
    
    # District URL pattern (Bayut uses slugs like /alexandria/district-name/)
    DISTRICT_URL_TEMPLATE = "https://www.bayut.eg/en/alexandria/{district_slug}/apartments-for-sale/"

    # Configuration
    DEFAULT_MAX_LISTINGS = 100  # Target number of listings per run
    SCROLL_BATCH_SIZE = 3       # Number of scrolls per batch
    SCROLL_DELAY = 3000         # ms to wait after each scroll
    PAGE_LOAD_TIMEOUT = 60000   # ms

    def __init__(self, district: Optional[str] = None, max_listings: int = DEFAULT_MAX_LISTINGS):
        super().__init__()
        self.target_district = district
        self.max_listings = max_listings
        self.listings_data: list[dict] = []

    @property
    def start_url(self) -> str:
        """Determine the starting URL based on configuration."""
        if self.target_district:
            # Convert district name to URL slug
            slug = self.target_district.lower().replace(" ", "-")
            return self.DISTRICT_URL_TEMPLATE.format(district_slug=slug)
        return self.BASE_URL

    async def scrape(self):
        """
        Main entry point. Navigate Bayut, intercept Algolia responses,
        extract listings with pagination, and upsert to DB.
        """
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser, context = await self._make_browser(p)
            page = await context.new_page()

            # Intercept Algolia responses
            page.on(
                "response",
                lambda resp: asyncio.create_task(
                    self._intercept_algolia(resp)
                ),
            )

            try:
                logger.info(f"Starting Bayut scrape: {self.start_url}")
                logger.info(f"Target: {self.max_listings} listings")
                if self.target_district:
                    logger.info(f"District filter: {self.target_district}")

                # Navigate to starting page
                await self._navigate_and_wait(page, self.start_url)
                
                # Keep scrolling until we have enough listings or no more results
                previous_count = 0
                scroll_attempts = 0
                max_scroll_attempts = 20  # Safety limit
                
                while len(self.listings_data) < self.max_listings and scroll_attempts < max_scroll_attempts:
                    logger.info(f"Listings so far: {len(self.listings_data)}/{self.max_listings}")
                    
                    # Scroll to trigger more Algolia calls
                    await self._scroll_page(page)
                    
                    # Check if we got new listings
                    if len(self.listings_data) == previous_count:
                        scroll_attempts += 1
                        if scroll_attempts >= 3:
                            logger.info("No new listings after 3 scroll attempts - stopping")
                            break
                    else:
                        scroll_attempts = 0
                        previous_count = len(self.listings_data)

                logger.info(f"Total intercepted: {len(self.listings_data)} raw listing entries")

                # Process and upsert
                processed_ids = set()
                success_count = 0
                error_count = 0
                
                for raw in self.listings_data:
                    external_id = str(raw.get("id", ""))
                    if not external_id or external_id in processed_ids:
                        continue
                    processed_ids.add(external_id)

                    try:
                        parsed = self._parse_listing(raw)
                        if parsed:
                            self.stats["listings_found"] += 1
                            self._upsert_listing(parsed)
                            success_count += 1
                    except Exception as e:
                        logger.warning(f"Failed to process listing {external_id}: {e}")
                        error_count += 1

                logger.info(f"Processed: {success_count} success, {error_count} errors")

            finally:
                await browser.close()

    async def _navigate_and_wait(self, page: Page, url: str):
        """Navigate to URL and wait for Algolia responses."""
        logger.info(f"Navigating to {url}...")
        await page.goto(url, wait_until="domcontentloaded", timeout=self.PAGE_LOAD_TIMEOUT)
        # Wait for initial Algolia call
        await page.wait_for_timeout(8000)

    async def _scroll_page(self, page: Page):
        """Scroll down to trigger more Algolia responses."""
        for i in range(self.SCROLL_BATCH_SIZE):
            await page.evaluate("window.scrollBy(0, 1000)")
            await page.wait_for_timeout(self.SCROLL_DELAY)

    async def _intercept_algolia(self, response):
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
            if len(body) < 1000:
                return

            data = json.loads(body)
            if not isinstance(data, dict) or "results" not in data:
                return

            # Algolia returns {"results": [{"hits": [...]}]}
            for result in data["results"]:
                hits = result.get("hits", [])
                if hits and isinstance(hits, list):
                    for hit in hits:
                        if hit.get("purpose") == "for-sale" or hit.get("price"):
                            self.listings_data.append(hit)

        except Exception:
            pass

    def _parse_listing(self, raw: dict) -> Optional[dict[str, Any]]:
        """Map a raw Bayut Algolia hit to our DB schema."""
        try:
            external_id = str(raw.get("id", ""))
            if not external_id:
                return None

            # Price
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

            # Title
            title = raw.get("title", "")

            # URL
            slug = raw.get("slug", "")
            ref = raw.get("referenceNumber", "")
            listing_url = None
            if slug:
                listing_url = f"https://www.bayut.eg/en/property/{slug}/"
            elif ref:
                listing_url = f"https://www.bayut.eg/en/property/{ref}/"

            # Photos
            photos = raw.get("photoList", [])
            media_urls = [p.get("url", "") for p in photos if p.get("url")]

            # Description
            description_parts = [title] if title else []
            if raw.get("amenities"):
                description_parts.append(f"Amenities: {', '.join(raw['amenities'])}")
            description = "\n".join(description_parts)

            # District extraction
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
                            location_name = name
                        elif level == 2:
                            district = normalize_district(name) or name
                            neighborhood = name
            
            # Fallback: search title for district
            if not district and title:
                for canonical, aliases in DISTRICT_ALIASES.items():
                    for alias in aliases:
                        if alias.lower() in title.lower():
                            district = canonical
                            break
                    if district:
                        break

            # If district filter was specified, only keep matching listings
            if self.target_district and district:
                target_normalized = normalize_district(self.target_district)
                if district != target_normalized:
                    return None

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
                "contacts": [],
                "media": media_urls,
                "status": "active",
            }

        except Exception as e:
            logger.warning(f"Failed to parse listing: {e}")
            return None


async def scrape_all_districts(max_listings_per_district: int = 50):
    """
    Scrape multiple Alexandria districts from Bayut.
    Focus on the most popular districts.
    """
    priority_districts = [
        "Smouha",
        "Sidi Gaber", 
        "Glym",
        "San Stefano",
        "Kafr Abdou",
        "Loran",
        "Miami",
        "Montaza",
        "Agami",
        "Ibrahimeya",
    ]
    
    total_new = 0
    total_found = 0
    
    for district in priority_districts:
        logger.info(f"\n{'='*50}")
        logger.info(f"Scraping district: {district}")
        logger.info(f"{'='*50}")
        
        try:
            scraper = BayutAPIScraper(district=district, max_listings=max_listings_per_district)
            await scraper.run()
            
            total_found += scraper.stats["listings_found"]
            total_new += scraper.stats["new_listings"]
            
            logger.info(f"District {district}: Found={scraper.stats['listings_found']} New={scraper.stats['new_listings']}")
            
            # Small delay between districts
            await asyncio.sleep(2)
            
        except Exception as e:
            logger.error(f"Failed to scrape {district}: {e}")
            continue
    
    logger.info(f"\n{'='*50}")
    logger.info(f"TOTAL: Found={total_found} New={total_new}")
    logger.info(f"{'='*50}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bayut property scraper")
    parser.add_argument("--district", help="Specific district to scrape (e.g., Smouha)")
    parser.add_argument("--max-listings", type=int, default=100, help="Max listings to scrape")
    parser.add_argument("--all-districts", action="store_true", help="Scrape all major districts")
    args = parser.parse_args()
    
    if args.all_districts:
        asyncio.run(scrape_all_districts(max_listings_per_district=args.max_listings))
    else:
        scraper = BayutAPIScraper(district=args.district, max_listings=args.max_listings)
        asyncio.run(scraper.run())
