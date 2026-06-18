"""
API Scraper Template

This is a template for building scrapers against discovered API endpoints.
Copy this file, fill in the endpoint details, and customize the parser.

Usage:
    cp scrapers/api_scraper_template.py scrapers/propertyfinder_api_scraper.py
    # Edit the file with your discovered endpoint
    uv run python -m scrapers.propertyfinder_api_scraper
"""

import os
from typing import Any

from scrapers.api_client import HiddenAPIClient
from scrapers.base_scraper import BaseScraper
from scrapers.db import DBClient


class APIScraperTemplate(BaseScraper):
    """
    Template for API-based scrapers.

    To use:
    1. Replace BASE_URL with your discovered API base URL
    2. Replace ENDPOINT with your discovered endpoint path
    3. Customize _parse_listing() to map API fields to your DB schema
    4. Rename the class (e.g., PropertyFinderAPIScraper)
    """

    # TODO: Fill these in after discovery
    BASE_URL = "https://api.example.com"
    ENDPOINT = "/v1/listings"

    # TODO: Add any required headers (auth tokens, etc.)
    CUSTOM_HEADERS = {}

    def __init__(self, db: DBClient | None = None):
        super().__init__(db)
        self.api_client = HiddenAPIClient(
            base_url=self.BASE_URL,
            bearer_token=os.environ.get("API_BEARER_TOKEN"),
            api_key_header=None,
            referer="https://www.example.com",
        )
        # Add custom headers
        for key, value in self.CUSTOM_HEADERS.items():
            self.api_client.session.headers[key] = value

    def run(self) -> dict[str, Any]:
        """
        Fetch listings from the API and upsert to DB.

        Returns stats dict with new_count, duplicate_count, error_count.
        """
        self.logger.info(f"Fetching listings from {self.BASE_URL}{self.ENDPOINT}")

        try:
            # TODO: Adjust params based on your discovered API
            params = {
                "page": 1,
                "limit": 50,
                # "location": "alexandria",
                # "property_type": "apartment",
            }

            response = self.api_client.session.get(
                f"{self.BASE_URL}{self.ENDPOINT}",
                params=params,
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()

            # TODO: Adjust based on your API response structure
            # Common patterns:
            # listings = data["results"]
            # listings = data["data"]["listings"]
            # listings = data
            listings = data.get("results", [])

            self.logger.info(f"Retrieved {len(listings)} listings from API")

            for listing in listings:
                try:
                    parsed = self._parse_listing(listing)
                    if parsed:
                        self.db_client.upsert_listing(parsed)
                        self.stats["new"] += 1
                except Exception as e:
                    self.logger.error(f"Error processing listing: {e}")
                    self.stats["errors"] += 1

        except Exception as e:
            self.logger.error(f"API request failed: {e}")
            self.stats["errors"] += 1

        return self.stats

    def _parse_listing(self, raw: dict) -> dict[str, Any] | None:
        """
        Parse a raw API response into your DB schema.

        TODO: Customize this based on your discovered API response structure.
        """
        # Example mapping - adjust field names to match your API
        try:
            return {
                "source_url": raw.get("url", "") or raw.get("permalink", ""),
                "title": raw.get("title", ""),
                "description": raw.get("description", ""),
                "price": self._parse_price(raw.get("price")),
                "currency": raw.get("currency", "EGP"),
                "bedrooms": raw.get("bedrooms") or raw.get("bedroom_count"),
                "bathrooms": raw.get("bathrooms") or raw.get("bathroom_count"),
                "area": raw.get("area") or raw.get("size_sqm"),
                "district_id": raw.get("district_id"),
                "property_type": raw.get("property_type", "apartment"),
                "transaction_type": raw.get("transaction_type", "sale"),
                "location_text": raw.get("location", ""),
                "source_name": "api_template",  # TODO: Change this
                "external_id": raw.get("id", ""),
            }
        except Exception as e:
            self.logger.error(f"Parse error: {e}")
            return None

    def _parse_price(self, price_raw: Any) -> float | None:
        """Extract numeric price from various formats."""
        if price_raw is None:
            return None
        if isinstance(price_raw, (int, float)):
            return float(price_raw)
        # Handle string formats like "1,250,000 EGP" or "1250000"
        cleaned = str(price_raw).replace(",", "").replace("EGP", "").replace("$", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            return None


if __name__ == "__main__":
    # Quick test - won't work without a real endpoint
    print("This is a template. Copy it and fill in your discovered API details.")
    print()
    print("Steps:")
    print("1. Run discovery: uv run python -m scrapers.discovery <url>")
    print("2. Filter traffic: uv run python scripts/filter_traffic.py <output.json>")
    print("3. Copy this template: cp scrapers/api_scraper_template.py scrapers/your_scraper.py")
    print("4. Fill in BASE_URL, ENDPOINT, and _parse_listing()")
    print("5. Test: uv run python -m scrapers.your_scraper")
