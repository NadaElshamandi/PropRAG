"""
scheduler.py
-------------
Prefect flow that runs all scrapers on a schedule.
Runs every 6 hours by default.

To run:
    python scheduler.py              # runs once immediately
    prefect deploy scheduler.py      # deploys as a Prefect managed flow
"""

import asyncio
from prefect import flow, task, get_run_logger
from prefect.schedules import IntervalSchedule
from datetime import timedelta

from propertyfinder_scraper import PropertyFinderScraper
from aqarmap_scraper import AqarmapScraper
from elbayt_scraper import ElbaytScraper


# ── Tasks (one per scraper) ──────────────────────────────────────────────────

@task(name="scrape-propertyfinder", retries=2, retry_delay_seconds=60)
async def run_propertyfinder():
    logger = get_run_logger()
    logger.info("Starting PropertyFinder scrape...")
    scraper = PropertyFinderScraper()
    await scraper.run()
    return scraper.stats


@task(name="scrape-aqarmap", retries=2, retry_delay_seconds=60)
async def run_aqarmap():
    logger = get_run_logger()
    logger.info("Starting Aqarmap scrape...")
    scraper = AqarmapScraper()
    await scraper.run()
    return scraper.stats


@task(name="scrape-elbayt", retries=2, retry_delay_seconds=60)
async def run_elbayt():
    logger = get_run_logger()
    logger.info("Starting Elbayt scrape...")
    scraper = ElbaytScraper()
    await scraper.run()
    return scraper.stats


# ── Main flow ────────────────────────────────────────────────────────────────

@flow(
    name="alexandria-real-estate-pipeline",
    description="Scrapes Alexandria apartment listings from all sources every 6 hours.",
)
async def main_pipeline():
    logger = get_run_logger()
    logger.info("Pipeline started — running all scrapers sequentially.")

    # Run sequentially to avoid hammering sites simultaneously
    pf_stats  = await run_propertyfinder()
    aq_stats  = await run_aqarmap()
    el_stats  = await run_elbayt()

    # Summary log
    total_new = (
        pf_stats.get("new_listings", 0)
        + aq_stats.get("new_listings", 0)
        + el_stats.get("new_listings", 0)
    )
    logger.info(f"Pipeline complete. Total new listings this run: {total_new}")
    return {
        "propertyfinder": pf_stats,
        "aqarmap":        aq_stats,
        "elbayt":         el_stats,
        "total_new":      total_new,
    }


# ── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Run once immediately
    asyncio.run(main_pipeline())
