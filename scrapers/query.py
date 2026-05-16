"""
query.py
--------
CLI tool for querying the PropRAG database via hybrid vector + metadata search.

Usage:
    uv run python -m scrapers.query "modern apartment in Smouha with sea view" --district Smouha --max-price 10000000
    uv run python -m scrapers.query "spacious villa near the beach" --bedrooms 4
"""

import argparse
import logging
import sys
from typing import Optional

from scrapers.db import DBClient
from scrapers.neighborhoods import list_canonical_districts, normalize_district

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
)
logger = logging.getLogger("query")


def format_price(price: Optional[int]) -> str:
    """Format EGP price with thousand separators."""
    if price is None:
        return "N/A"
    return f"EGP {price:,.0f}"


def format_area(area: Optional[float]) -> str:
    """Format area in sqm."""
    if area is None:
        return "N/A"
    return f"{area:.0f} m²"


def print_results(results: list[dict], query: str):
    """Pretty-print search results."""
    if not results:
        print(f"\nNo results found for: \"{query}\"")
        return

    print(f"\n{'=' * 80}")
    print(f"Query: \"{query}\"")
    print(f"Found {len(results)} result(s)")
    print(f"{'=' * 80}\n")

    for i, r in enumerate(results, 1):
        title = r.get("title") or "No title"
        district = r.get("district") or "Unknown district"
        price = r.get("price_egp")
        area = r.get("area_sqm")
        bedrooms = r.get("bedrooms")
        bathrooms = r.get("bathrooms")
        similarity = r.get("similarity", 0)

        print(f"  {i}. {title}")
        print(f"     📍 {district}  |  🏷️  {format_price(price)}  |  📐 {format_area(area)}")
        if bedrooms is not None:
            print(f"     🛏️  {bedrooms} BR  |  🚿 {bathrooms or 'N/A'} BA")
        print(f"     🔍 Similarity: {similarity:.3f}")
        print()


def print_market_context(db: DBClient, district: Optional[str]):
    """Show average price per sqm for the queried district."""
    if not district:
        return

    norm = normalize_district(district)
    if not norm:
        return

    try:
        # Fetch active listings in this district with price + area
        res = (
            db.supabase.table("listings")
            .select("price_egp, area_sqm, locations!inner(district)")
            .eq("status", "active")
            .eq("locations.district", norm)
            .execute()
        )
        rows = res.data or []

        valid = [r for r in rows if r.get("price_egp") and r.get("area_sqm")]
        if not valid:
            return

        avg_price = sum(r["price_egp"] for r in valid) / len(valid)
        avg_area = sum(r["area_sqm"] for r in valid) / len(valid)
        avg_psm = avg_price / avg_area if avg_area > 0 else 0

        print(f"📊 Market context for {norm}:")
        print(f"   Average price: {format_price(int(avg_price))}")
        print(f"   Average area: {avg_area:.0f} m²")
        print(f"   Average price/m²: EGP {avg_psm:,.0f}")
        print(f"   Sample size: {len(valid)} listings")
        print()
    except Exception as e:
        logger.warning(f"Could not fetch market context: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Query the PropRAG real estate database.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s "modern apartment in Smouha" --district Smouha
  %(prog)s "cheap studio near the sea" --max-price 2000000
  %(prog)s "villa with garden" --bedrooms 4 --district Kafr Abdou
        """,
    )
    parser.add_argument("query", help="Natural language search query")
    parser.add_argument("--district", help="Filter by district (e.g., Smouha)")
    parser.add_argument("--min-price", type=int, help="Minimum price in EGP")
    parser.add_argument("--max-price", type=int, help="Maximum price in EGP")
    parser.add_argument("--bedrooms", type=int, help="Minimum number of bedrooms")
    parser.add_argument("--limit", type=int, default=10, help="Max results (default: 10)")
    parser.add_argument(
        "--list-districts",
        action="store_true",
        help="Print all known districts and exit",
    )

    args = parser.parse_args()

    if args.list_districts:
        print("Known districts:")
        for d in sorted(list_canonical_districts()):
            print(f"  - {d}")
        sys.exit(0)

    db = DBClient()

    # Validate district if provided
    if args.district:
        norm = normalize_district(args.district)
        if not norm:
            logger.error(f"Unknown district: {args.district}")
            print(f"Known districts: {', '.join(list_canonical_districts())}")
            sys.exit(1)

    # Run search
    results = db.search_listings(
        args.query,
        district=args.district,
        min_price=args.min_price,
        max_price=args.max_price,
        bedrooms=args.bedrooms,
        limit=args.limit,
    )

    # Print market context
    print_market_context(db, args.district)

    # Print results
    print_results(results, args.query)


if __name__ == "__main__":
    main()
