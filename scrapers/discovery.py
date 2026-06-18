"""
Network Traffic Discovery Script using Playwright.

Navigates a real estate website, performs interactions,
and captures all XHR/Fetch network traffic to a JSON file.

Usage:
    uv run python -m scrapers.discovery https://www.propertyfinder.eg/en/buy/alexandria/apartments-for-sale.html

Output:
    data/discovery/<domain>_<timestamp>.json
"""

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright

# Where to save captured traffic
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "discovery"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


class TrafficCapture:
    """Captures network requests and responses via Playwright."""

    def __init__(self):
        self.captured = []

    async def on_response(self, response):
        """Capture every response that looks like an API call."""
        try:
            # Only care about XHR/fetch (not images, CSS, etc.)
            resource_type = response.request.resource_type
            if resource_type not in ("xhr", "fetch", "document"):
                return

            headers = await response.all_headers()
            content_type = headers.get("content-type", "").lower()

            # Skip non-JSON responses early
            if "json" not in content_type and "graphql" not in content_type:
                return

            # Try to get the response body
            try:
                body = await response.text()
                if len(body) > 500_000:  # Skip huge responses
                    body = body[:500_000] + "...[truncated]"
            except Exception:
                body = "<unable to read body>"

            req = response.request

            self.captured.append({
                "url": req.url,
                "method": req.method,
                "resource_type": resource_type,
                "status": response.status,
                "content_type": content_type,
                "headers": dict(req.headers),
                "response_headers": dict(headers),
                "body_preview": body[:2000] if body else "",
                "body_size": len(body) if body else 0,
                "timestamp": datetime.now().isoformat(),
            })

        except Exception:
            # Don't let a single bad response crash the capture
            pass


async def discover(url: str, headless: bool = False, timeout: int = 30):
    """
    Navigate a website and capture network traffic.

    Args:
        url: The starting URL
        headless: Run browser headless (no GUI)
        timeout: Seconds to wait after interactions for dynamic requests
    """
    capture = TrafficCapture()

    print(f"🚀 Starting discovery for: {url}")
    print(f"   Headless: {headless}")
    print(f"   Post-interaction timeout: {timeout}s")
    print()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )

        page = await context.new_page()

        # Attach network listener
        page.on("response", lambda r: asyncio.create_task(capture.on_response(r)))

        # Navigate to target
        print(f"📡 Navigating to {url}...")
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)

        # Wait for initial load
        print("⏳ Waiting for page load...")
        await page.wait_for_timeout(3000)

        # Try to find and click common elements to trigger API calls
        print("🔍 Triggering interactions...")

        # Scroll down to trigger infinite scroll / lazy loading
        print("   Scrolling down...")
        for _ in range(3):
            await page.evaluate("window.scrollBy(0, 800)")
            await page.wait_for_timeout(2000)

        # Try pagination - look for page number links
        print("   Looking for pagination...")
        pagination_selectors = [
            "a[aria-label='Next']",
            "a:has-text('Next')",
            "button:has-text('Next')",
            "a[href*='page=']",
            "a[href*='/page/']",
            "[data-testid='pagination-next']",
            "[class*='pagination'] a",
        ]

        for selector in pagination_selectors:
            try:
                elem = await page.query_selector(selector)
                if elem and await elem.is_visible():
                    print(f"   Clicking pagination: '{selector}'...")
                    # Clear capture to isolate what this click triggers
                    before_count = len(capture.captured)
                    await elem.click()
                    await page.wait_for_timeout(3000)
                    after_count = len(capture.captured)
                    if after_count > before_count:
                        print(f"     📡 Captured {after_count - before_count} new responses!")
                    break
            except Exception:
                pass

        # Try filters - look for common filter elements
        print("   Looking for filters...")
        filter_selectors = [
            "button:has-text('Filter')",
            "button:has-text('Filters')",
            "a:has-text('Filter')",
            "[data-testid='filter-button']",
            "[class*='filter'] button",
        ]

        for selector in filter_selectors:
            try:
                elem = await page.query_selector(selector)
                if elem and await elem.is_visible():
                    print(f"   Clicking filter: '{selector}'...")
                    before_count = len(capture.captured)
                    await elem.click()
                    await page.wait_for_timeout(3000)
                    after_count = len(capture.captured)
                    if after_count > before_count:
                        print(f"     📡 Captured {after_count - before_count} new responses!")
                    break
            except Exception:
                pass

        # Try clicking specific page numbers if pagination exists
        print("   Looking for page numbers...")
        try:
            page_links = await page.query_selector_all("a[href*='page='], a[href*='/page/'], [class*='pagination'] a")
            for link in page_links[:3]:  # Try first 3 page links
                if await link.is_visible():
                    text = await link.text_content()
                    if text and text.strip().isdigit():
                        print(f"   Clicking page {text.strip()}...")
                        before_count = len(capture.captured)
                        await link.click()
                        await page.wait_for_timeout(3000)
                        after_count = len(capture.captured)
                        if after_count > before_count:
                            print(f"     📡 Captured {after_count - before_count} new responses!")
                        break
        except Exception:
            pass

        # Try sort dropdown
        print("   Looking for sort options...")
        sort_selectors = [
            "select",
            "[data-testid='sort-dropdown']",
            "button:has-text('Sort')",
            "[class*='sort'] button",
        ]

        for selector in sort_selectors:
            try:
                elem = await page.query_selector(selector)
                if elem and await elem.is_visible():
                    print(f"   Interacting with sort: '{selector}'...")
                    before_count = len(capture.captured)
                    await elem.click()
                    await page.wait_for_timeout(2000)
                    # Try clicking a sort option
                    options = await page.query_selector_all("[role='option'], li, a")
                    for opt in options[:3]:
                        if await opt.is_visible():
                            await opt.click()
                            await page.wait_for_timeout(2000)
                            break
                    after_count = len(capture.captured)
                    if after_count > before_count:
                        print(f"     📡 Captured {after_count - before_count} new responses!")
                    break
            except Exception:
                pass

        # Wait for dynamic requests to complete
        print(f"⏳ Waiting {timeout}s for dynamic requests...")
        await page.wait_for_timeout(timeout * 1000)

        # Get captured traffic
        traffic = capture.captured
        print(f"\n📊 Captured {len(traffic)} API-like responses")

        # Save to file
        domain = urlparse(url).netloc.replace("www.", "")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{domain}_{timestamp}.json"
        filepath = OUTPUT_DIR / filename

        output = {
            "source_url": url,
            "captured_at": datetime.now().isoformat(),
            "total_responses": len(traffic),
            "responses": traffic,
        }

        with open(filepath, "w") as f:
            json.dump(output, f, indent=2, default=str)

        print(f"💾 Saved to: {filepath}")

        # Print summary
        print(f"\n📋 Summary:")
        print(f"   Total responses: {len(traffic)}")

        if traffic:
            sizes = [r["body_size"] for r in traffic]
            print(f"   Avg body size: {sum(sizes)/len(sizes):.0f} bytes")
            print(f"   Largest: {max(sizes)} bytes")

            # Show top candidates
            by_size = sorted(traffic, key=lambda x: x["body_size"], reverse=True)[:10]
            print(f"\n🎯 Top candidates by response size:")
            for i, req in enumerate(by_size, 1):
                print(f"   {i}. {req['method']} {req['url'][:80]}... ({req['body_size']} bytes, status: {req['status']})")

        await browser.close()
        print("\n✅ Discovery complete")
        return filepath


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: uv run python -m scrapers.discovery <url>")
        print("Example: uv run python -m scrapers.discovery https://www.propertyfinder.eg/en/buy/alexandria/apartments-for-sale.html")
        sys.exit(1)

    target_url = sys.argv[1]
    headless = "--headless" in sys.argv

    asyncio.run(discover(target_url, headless=headless))
