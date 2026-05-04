"""
propertyfinder_scraper.py
--------------------------
Scrapes apartments for sale in Alexandria from propertyfinder.eg

Target URL pattern:
  https://www.propertyfinder.eg/en/buy/alexandria/apartments-for-sale.html?page=N

Known data structure (observed from live site):
  - Listing cards rendered server-side, each inside an article element
  - Price, beds, baths, area, neighborhood visible on card
  - Detail page has full description, contact info, photo gallery
"""

import asyncio
import re
from typing import Optional

from playwright.async_api import async_playwright, Page, ElementHandle

from base_scraper import BaseScraper


class PropertyFinderScraper(BaseScraper):

    source_name = "propertyfinder"

    BASE_SEARCH_URL = (
        "https://www.propertyfinder.eg/en/buy/alexandria/"
        "apartments-for-sale.html?page={page}"
    )

    MAX_PAGES = 50          # safety ceiling (~25 listings/page = 1,250 max)
    DELAY_BETWEEN_PAGES = 3 # seconds — be polite
    DELAY_BETWEEN_DETAILS = 2

    # ── CSS selectors ────────────────────────────────────────────────────────
    # These are based on PropertyFinder EG's observed HTML structure.
    # If the site updates its markup, update these selectors.

    SEL_CARD           = "article[data-testid='property-card']"
    SEL_CARD_LINK      = "a[data-testid='property-card-link']"
    SEL_CARD_TITLE     = "[data-testid='property-card-title']"
    SEL_CARD_PRICE     = "[data-testid='property-card-price']"
    SEL_CARD_BEDS      = "[aria-label*='bedroom'], [data-testid='property-card-spec-bedroom']"
    SEL_CARD_BATHS     = "[aria-label*='bathroom'], [data-testid='property-card-spec-bathroom']"
    SEL_CARD_AREA      = "[aria-label*='area'], [data-testid='property-card-spec-area']"
    SEL_CARD_LOCATION  = "[data-testid='property-card-location']"

    SEL_DETAIL_DESC    = "[data-testid='property-description']"
    SEL_DETAIL_PHONE   = "[data-testid='call-button'], a[href^='tel:']"
    SEL_DETAIL_PHOTOS  = "img[data-testid='property-gallery-image'], .gallery img"
    SEL_DETAIL_FLOOR   = "[aria-label*='floor'], [data-testid*='floor']"
    SEL_DETAIL_FINISH  = "[aria-label*='finishing'], [data-testid*='finishing']"

    SEL_NEXT_PAGE      = "a[aria-label='Next page'], [data-testid='pagination-next']"

    # ── Main entry point ─────────────────────────────────────────────────────

    async def scrape(self):
        async with async_playwright() as pw:
            browser, context = await self._make_browser(pw)
            page = await context.new_page()

            try:
                for page_num in range(1, self.MAX_PAGES + 1):
                    url = self.BASE_SEARCH_URL.format(page=page_num)
                    self.logger.info(f"Scraping page {page_num}: {url}")

                    cards = await self._scrape_listing_page(page, url)
                    if not cards:
                        self.logger.info(f"No cards found on page {page_num} — stopping.")
                        break

                    self.stats["listings_found"] += len(cards)

                    for card in cards:
                        try:
                            listing_data = await self._process_card(page, card)
                            if listing_data:
                                self._upsert_listing(listing_data)
                        except Exception as e:
                            self.logger.warning(f"Failed to process card: {e}")
                            continue

                    # Check if there's a next page
                    has_next = await page.query_selector(self.SEL_NEXT_PAGE)
                    if not has_next:
                        self.logger.info("No next page — pagination complete.")
                        break

                    await asyncio.sleep(self.DELAY_BETWEEN_PAGES)

            finally:
                await browser.close()

    # ── Page-level scraping ──────────────────────────────────────────────────

    async def _scrape_listing_page(self, page: Page, url: str) -> list:
        """Navigate to a search results page and return all listing card elements."""
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            # Wait for cards to appear
            await page.wait_for_selector(self.SEL_CARD, timeout=15_000)
        except Exception as e:
            self.logger.warning(f"Page load failed or no listings: {e}")
            return []

        return await page.query_selector_all(self.SEL_CARD)

    # ── Card processing ──────────────────────────────────────────────────────

    async def _process_card(self, browser_page: Page, card: ElementHandle) -> Optional[dict]:
        """
        Extract summary data from a listing card, then visit the detail page
        for full data. Returns a dict ready for _upsert_listing().
        """
        # Extract the listing URL and external ID from the card
        link_el = await card.query_selector(self.SEL_CARD_LINK)
        if not link_el:
            return None

        href = await link_el.get_attribute("href")
        if not href:
            return None

        full_url = href if href.startswith("http") else f"https://www.propertyfinder.eg{href}"

        # Extract external ID from URL
        # URL pattern: /en/buy/alexandria/apartments-for-sale-smouha-12345678.html
        external_id = self._extract_id_from_url(full_url)
        if not external_id:
            return None

        # Quick card-level extraction (avoids loading detail page for dupes)
        title_el    = await card.query_selector(self.SEL_CARD_TITLE)
        price_el    = await card.query_selector(self.SEL_CARD_PRICE)
        beds_el     = await card.query_selector(self.SEL_CARD_BEDS)
        baths_el    = await card.query_selector(self.SEL_CARD_BATHS)
        area_el     = await card.query_selector(self.SEL_CARD_AREA)
        location_el = await card.query_selector(self.SEL_CARD_LOCATION)

        title    = await self._text(title_el)
        price    = self._clean_price(await self._text(price_el))
        beds     = self._clean_int(await self._text(beds_el))
        baths    = self._clean_int(await self._text(baths_el))
        area     = self._clean_area(await self._text(area_el))
        location = await self._text(location_el)

        # Parse location string "Neighborhood, District, Alexandria"
        location_parts = [p.strip() for p in (location or "").split(",")]
        neighborhood = location_parts[0] if len(location_parts) > 0 else None
        district     = location_parts[1] if len(location_parts) > 1 else None

        # Visit detail page for description, photos, contact
        detail = await self._scrape_detail_page(browser_page, full_url)

        return {
            "external_id":   external_id,
            "listing_url":   full_url,
            "title":         title,
            "price_egp":     price,
            "bedrooms":      beds,
            "bathrooms":     baths,
            "area_sqm":      area,
            "description":   detail.get("description"),
            "finishing":     detail.get("finishing"),
            "floor":         detail.get("floor"),
            "status":        "active",
            "media":         detail.get("photos", []),
            "contacts":      detail.get("contacts", []),
            "location": {
                "neighborhood": neighborhood,
                "district":     district,
                "raw_address":  location,
            },
        }

    # ── Detail page scraping ─────────────────────────────────────────────────

    async def _scrape_detail_page(self, page: Page, url: str) -> dict:
        """Visit the individual listing page and extract full details."""
        await asyncio.sleep(self.DELAY_BETWEEN_DETAILS)

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        except Exception as e:
            self.logger.warning(f"Detail page failed: {url} — {e}")
            return {}

        result = {}

        # Description
        desc_el = await page.query_selector(self.SEL_DETAIL_DESC)
        result["description"] = await self._text(desc_el)

        # Floor
        floor_el = await page.query_selector(self.SEL_DETAIL_FLOOR)
        result["floor"] = await self._text(floor_el)

        # Finishing
        finish_el = await page.query_selector(self.SEL_DETAIL_FINISH)
        result["finishing"] = await self._text(finish_el)

        # Photos (first 8 only — enough for the DB, don't hammer their CDN)
        photo_els = await page.query_selector_all(self.SEL_DETAIL_PHOTOS)
        photos = []
        for el in photo_els[:8]:
            src = await el.get_attribute("src") or await el.get_attribute("data-src")
            if src and src.startswith("http"):
                photos.append(src)
        result["photos"] = photos

        # Phone number
        phone_els = await page.query_selector_all(self.SEL_DETAIL_PHONE)
        contacts = []
        seen_phones = set()
        for el in phone_els:
            href = await el.get_attribute("href") or ""
            phone = href.replace("tel:", "").strip()
            if phone and phone not in seen_phones:
                seen_phones.add(phone)
                contacts.append({"phone": phone, "type": "unknown"})
        result["contacts"] = contacts

        return result

    # ── Utility helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _extract_id_from_url(url: str) -> Optional[str]:
        """
        Extract the numeric listing ID from a PropertyFinder URL.
        e.g. .../apartments-for-sale-smouha-12345678.html → '12345678'
        """
        match = re.search(r"-(\d{6,12})\.html", url)
        return match.group(1) if match else None

    @staticmethod
    async def _text(el: Optional[ElementHandle]) -> Optional[str]:
        """Safely get inner text from an element."""
        if el is None:
            return None
        text = await el.inner_text()
        return text.strip() if text else None


# ── Run standalone ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    scraper = PropertyFinderScraper()
    asyncio.run(scraper.run())
