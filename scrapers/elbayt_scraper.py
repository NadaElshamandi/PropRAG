"""
elbayt_scraper.py
------------------
Scrapes apartments for sale in Alexandria from elbayt.com

Target URL pattern:
  https://www.elbayt.com/en/properties/for-sale/alexandria?page=N

Elbayt tends to have well-structured, data-rich listings with
consistent field labeling — good for clean extraction.
"""

import asyncio
import re
from typing import Optional

from playwright.async_api import async_playwright, Page, ElementHandle

from base_scraper import BaseScraper


class ElbaytScraper(BaseScraper):

    source_name = "elbayt"

    BASE_SEARCH_URL = (
        "https://www.elbayt.com/en/properties/for-sale/alexandria"
        "?property_type=apartment&page={page}"
    )

    MAX_PAGES             = 50
    DELAY_BETWEEN_PAGES   = 3
    DELAY_BETWEEN_DETAILS = 2

    # ── CSS selectors ────────────────────────────────────────────────────────

    SEL_CARD           = ".property-card, [class*='PropertyCard'], .listing-item"
    SEL_CARD_LINK      = "a.property-card__link, a[class*='PropertyCard__link'], a.listing-item__link"
    SEL_CARD_TITLE     = ".property-card__title, [class*='PropertyCard__title'], h2.listing-title"
    SEL_CARD_PRICE     = ".property-card__price, [class*='price'], .listing-price"
    SEL_CARD_BEDS      = "[class*='bed'], [aria-label*='bed']"
    SEL_CARD_BATHS     = "[class*='bath'], [aria-label*='bath']"
    SEL_CARD_AREA      = "[class*='area'], [aria-label*='area'], [class*='size']"
    SEL_CARD_LOCATION  = ".property-card__location, [class*='location'], .listing-location"

    SEL_DETAIL_DESC    = ".property-description, [class*='description'], #property-description"
    SEL_DETAIL_PHONE   = "a[href^='tel:'], [class*='phone'], [class*='contact']"
    SEL_DETAIL_PHOTOS  = ".property-gallery img, [class*='gallery'] img, .carousel img"
    SEL_DETAIL_FLOOR   = "[class*='floor'], [data-label='Floor']"
    SEL_DETAIL_FINISH  = "[class*='finish'], [data-label*='Finish']"
    SEL_DETAIL_SPECS   = ".property-specs li, [class*='specs'] li, .property-features li"

    SEL_NEXT_PAGE      = "a[rel='next'], .pagination-next, [aria-label='Next page']"

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
                        self.logger.info("No cards found — stopping.")
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

                    has_next = await page.query_selector(self.SEL_NEXT_PAGE)
                    if not has_next:
                        self.logger.info("No next page — done.")
                        break

                    await asyncio.sleep(self.DELAY_BETWEEN_PAGES)

            finally:
                await browser.close()

    # ── Page-level scraping ──────────────────────────────────────────────────

    async def _scrape_listing_page(self, page: Page, url: str) -> list:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            await page.wait_for_selector(self.SEL_CARD, timeout=15_000)
        except Exception as e:
            self.logger.warning(f"Page load failed: {e}")
            return []

        return await page.query_selector_all(self.SEL_CARD)

    # ── Card processing ──────────────────────────────────────────────────────

    async def _process_card(self, browser_page: Page, card: ElementHandle) -> Optional[dict]:
        link_el = await card.query_selector(self.SEL_CARD_LINK)
        if not link_el:
            return None

        href = await link_el.get_attribute("href")
        if not href:
            return None

        full_url = href if href.startswith("http") else f"https://www.elbayt.com{href}"
        external_id = self._extract_id_from_url(full_url)
        if not external_id:
            return None

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

        location_parts = [p.strip() for p in re.split(r"[,|/·]", location or "") if p.strip()]
        neighborhood = location_parts[0] if len(location_parts) > 0 else None
        district     = location_parts[1] if len(location_parts) > 1 else None

        detail = await self._scrape_detail_page(browser_page, full_url)

        return {
            "external_id":  external_id,
            "listing_url":  full_url,
            "title":        title,
            "price_egp":    price,
            "bedrooms":     beds,
            "bathrooms":    baths,
            "area_sqm":     area,
            "description":  detail.get("description"),
            "finishing":    detail.get("finishing"),
            "floor":        detail.get("floor"),
            "has_elevator": detail.get("has_elevator"),
            "has_parking":  detail.get("has_parking"),
            "status":       "active",
            "media":        detail.get("photos", []),
            "contacts":     detail.get("contacts", []),
            "location": {
                "neighborhood": neighborhood,
                "district":     district,
                "raw_address":  location,
            },
        }

    # ── Detail page scraping ─────────────────────────────────────────────────

    async def _scrape_detail_page(self, page: Page, url: str) -> dict:
        await asyncio.sleep(self.DELAY_BETWEEN_DETAILS)

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        except Exception as e:
            self.logger.warning(f"Detail page failed: {url} — {e}")
            return {}

        result = {}

        desc_el = await page.query_selector(self.SEL_DETAIL_DESC)
        result["description"] = await self._text(desc_el)

        floor_el = await page.query_selector(self.SEL_DETAIL_FLOOR)
        result["floor"] = await self._text(floor_el)

        finish_el = await page.query_selector(self.SEL_DETAIL_FINISH)
        result["finishing"] = await self._text(finish_el)

        # Elbayt often lists amenities as bullet points — scan them
        spec_els = await page.query_selector_all(self.SEL_DETAIL_SPECS)
        spec_texts = []
        for el in spec_els:
            t = await self._text(el)
            if t:
                spec_texts.append(t.lower())

        result["has_elevator"] = any("elevator" in s or "lift" in s for s in spec_texts)
        result["has_parking"]  = any("parking" in s or "garage" in s for s in spec_texts)

        # Photos
        photo_els = await page.query_selector_all(self.SEL_DETAIL_PHOTOS)
        photos = []
        for el in photo_els[:8]:
            src = await el.get_attribute("src") or await el.get_attribute("data-src")
            if src and src.startswith("http"):
                photos.append(src)
        result["photos"] = photos

        # Phone
        phone_els = await page.query_selector_all(self.SEL_DETAIL_PHONE)
        contacts = []
        seen = set()
        for el in phone_els:
            href = await el.get_attribute("href") or ""
            phone = href.replace("tel:", "").strip()
            if phone and phone not in seen:
                seen.add(phone)
                contacts.append({"phone": phone, "type": "unknown"})
        result["contacts"] = contacts

        return result

    # ── Utility helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _extract_id_from_url(url: str) -> Optional[str]:
        """
        Elbayt URL pattern: /en/properties/for-sale/alexandria/apartment/slug-12345
        """
        match = re.search(r"-(\d{4,12})(?:/|\?|$|#)", url)
        return match.group(1) if match else None

    @staticmethod
    async def _text(el: Optional[ElementHandle]) -> Optional[str]:
        if el is None:
            return None
        text = await el.inner_text()
        return text.strip() if text else None


# ── Run standalone ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    scraper = ElbaytScraper()
    asyncio.run(scraper.run())
