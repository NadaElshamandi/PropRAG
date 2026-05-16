"""
facebook_importer.py
--------------------
Manual CSV importer for Facebook Marketplace listings.

Facebook Marketplace aggressively blocks headless browsers, so this takes a
manually-exported CSV and normalizes/upserts it into the PropRAG database
with the same district normalization and embedding pipeline as the scrapers.

Usage:
    uv run python -m scrapers.facebook_importer data/facebook_listings.csv

Expected CSV columns (header row required):
    title, price_egp, bedrooms, bathrooms, area_sqm, district,
    neighborhood, listing_url, description, contact_phone

Optional columns (will use empty defaults):
    floor, finishing

Example CSV row:
    title,price_egp,bedrooms,bathrooms,area_sqm,district,neighborhood,listing_url,description,contact_phone
    "Modern apt in Smouha",8500000,3,2,160,Smouha,Smouha,https://fb.com/...,"Great view",01001234567
"""

import argparse
import csv
import logging
import sys
from pathlib import Path

from scrapers.db import DBClient
from scrapers.neighborhoods import normalize_district

logger = logging.getLogger("facebook_importer")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
)


def parse_csv(path: Path) -> list[dict]:
    """Read a Facebook Marketplace CSV and return raw row dicts."""
    rows = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({k.strip(): v.strip() for k, v in row.items()})
    return rows


def row_to_listing(row: dict) -> dict:
    """Convert a CSV row to the standardized listing dict for DBClient."""
    external_id = _extract_fb_id(row.get("listing_url", ""))
    if not external_id:
        # Fallback: hash the title + price as a synthetic ID
        external_id = str(hash(f"{row.get('title','')}{row.get('price_egp','')}"))[:12]

    district = normalize_district(row.get("district", ""))
    neighborhood = row.get("neighborhood", "")

    return {
        "external_id": external_id,
        "listing_url": row.get("listing_url", ""),
        "title": row.get("title", ""),
        "price_egp": _parse_int(row.get("price_egp", "")),
        "bedrooms": _parse_int(row.get("bedrooms", "")),
        "bathrooms": _parse_int(row.get("bathrooms", "")),
        "area_sqm": _parse_float(row.get("area_sqm", "")),
        "description": row.get("description", ""),
        "floor": row.get("floor") or None,
        "finishing": row.get("finishing") or None,
        "status": "active",
        "media": [],  # Facebook photos are not easily exportable in CSV
        "contacts": (
            [{"phone": row["contact_phone"].strip(), "type": "unknown"}]
            if row.get("contact_phone", "").strip()
            else []
        ),
        "location": {
            "district": district,
            "neighborhood": neighborhood or district,
            "raw_address": f"{neighborhood}, {district}, Alexandria",
        },
    }


def _extract_fb_id(url: str) -> str | None:
    """Extract a numeric listing ID from a Facebook Marketplace URL."""
    import re

    match = re.search(r"/item/(\d+)/", url)
    if match:
        return match.group(1)
    # Also try permalink format
    match = re.search(r"[&?]id=(\d+)", url)
    if match:
        return match.group(1)
    return None


def _parse_int(raw: str) -> int | None:
    digits = "".join(c for c in raw if c.isdigit())
    return int(digits) if digits else None


def _parse_float(raw: str) -> float | None:
    digits = "".join(c for c in raw if c.isdigit() or c == ".")
    return float(digits) if digits else None


def main():
    parser = argparse.ArgumentParser(
        description="Import Facebook Marketplace CSV into PropRAG",
    )
    parser.add_argument("csv_file", help="Path to CSV file")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and print without inserting into DB",
    )
    args = parser.parse_args()

    path = Path(args.csv_file)
    if not path.exists():
        logger.error(f"File not found: {path}")
        sys.exit(1)

    raw_rows = parse_csv(path)
    logger.info(f"Parsed {len(raw_rows)} rows from {path}")

    if not raw_rows:
        logger.warning("No rows found.")
        sys.exit(0)

    db = DBClient()
    source_id = db.get_source_id("facebook")

    new_count = 0
    dupe_count = 0
    error_count = 0

    for row in raw_rows:
        listing = row_to_listing(row)
        if args.dry_run:
            print(f"Would upsert: {listing['external_id']} — {listing['title'][:50]}")
            continue

        _, is_new = db.upsert_listing(source_id, listing)
        if is_new:
            new_count += 1
        elif _ is None:
            error_count += 1
        else:
            dupe_count += 1

    logger.info(
        f"Done. New={new_count} Dupes={dupe_count} Errors={error_count}"
    )


if __name__ == "__main__":
    main()
