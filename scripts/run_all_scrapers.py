"""
run_all_scrapers.py
-------------------
Combined scraper runner for PropRAG.

Runs all active scrapers in sequence:
1. PropertyFinder (HTML cards - high volume)
2. Bayut (Algolia API - rich data)

Usage:
    uv run python -m scripts.run_all_scrapers
    uv run python -m scripts.run_all_scrapers --bayut-only
    uv run python -m scripts.run_all_scrapers --propertyfinder-only
"""

import argparse
import asyncio
import logging
import sys
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, str(__file__).parent.parent)

from scrapers.propertyfinder_scraper import PropertyFinderScraper
from scrapers.bayut_scraper import BayutAPIScraper, scrape_all_districts

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("CombinedRunner")


async def run_propertyfinder():
    """Run PropertyFinder scraper."""
    logger.info("\n" + "="*60)
    logger.info("STARTING: PropertyFinder Scraper")
    logger.info("="*60)
    
    try:
        scraper = PropertyFinderScraper()
        await scraper.run()
        logger.info(f"PropertyFinder complete: Found={scraper.stats['listings_found']} New={scraper.stats['new_listings']}")
        return scraper.stats
    except Exception as e:
        logger.error(f"PropertyFinder failed: {e}")
        return None


async def run_bayut(district: str = None, max_listings: int = 100):
    """Run Bayut scraper."""
    logger.info("\n" + "="*60)
    logger.info("STARTING: Bayut Scraper")
    logger.info("="*60)
    
    try:
        scraper = BayutAPIScraper(district=district, max_listings=max_listings)
        await scraper.run()
        logger.info(f"Bayut complete: Found={scraper.stats['listings_found']} New={scraper.stats['new_listings']}")
        return scraper.stats
    except Exception as e:
        logger.error(f"Bayut failed: {e}")
        return None


async def run_bayut_all_districts(max_listings_per_district: int = 50):
    """Run Bayut scraper across all districts."""
    logger.info("\n" + "="*60)
    logger.info("STARTING: Bayut Multi-District Scraper")
    logger.info("="*60)
    
    try:
        await scrape_all_districts(max_listings_per_district=max_listings_per_district)
    except Exception as e:
        logger.error(f"Bayut multi-district failed: {e}")


async def main():
    parser = argparse.ArgumentParser(description="Run all PropRAG scrapers")
    parser.add_argument("--propertyfinder-only", action="store_true", help="Only run PropertyFinder")
    parser.add_argument("--bayut-only", action="store_true", help="Only run Bayut")
    parser.add_argument("--bayut-district", help="Scrape specific Bayut district")
    parser.add_argument("--bayut-all-districts", action="store_true", help="Scrape all Bayut districts")
    parser.add_argument("--max-listings", type=int, default=100, help="Max listings per scraper")
    args = parser.parse_args()
    
    start_time = datetime.now()
    logger.info(f"Starting combined scraper run at {start_time}")
    
    # Determine which scrapers to run
    run_pf = not args.bayut_only
    run_bayut = not args.propertyfinder_only
    
    results = {}
    
    if run_pf:
        results["propertyfinder"] = await run_propertyfinder()
        await asyncio.sleep(5)  # Brief pause between scrapers
    
    if run_bayut:
        if args.bayut_all_districts:
            await run_bayut_all_districts(max_listings_per_district=args.max_listings)
        else:
            results["bayut"] = await run_bayut(
                district=args.bayut_district,
                max_listings=args.max_listings
            )
    
    # Summary
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    
    logger.info("\n" + "="*60)
    logger.info("SCRAPER RUN COMPLETE")
    logger.info("="*60)
    logger.info(f"Duration: {duration:.1f}s")
    
    for name, stats in results.items():
        if stats:
            logger.info(f"{name}: Found={stats.get('listings_found', 0)} New={stats.get('new_listings', 0)} Dupes={stats.get('duplicates_skipped', 0)}")
    
    logger.info("="*60)


if __name__ == "__main__":
    asyncio.run(main())
