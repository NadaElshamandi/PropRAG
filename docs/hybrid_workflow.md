# 🔍 Hybrid API Discovery Workflow

## Overview
This workflow uses **nodriver** (stealth browser automation) for API discovery and **requests** (HTTP library) for execution.

**Why this approach?**
- nodriver bypasses anti-bot protections during discovery
- requests is fast, simple, and reliable for repeated API calls
- You learn CDP/network interception without over-engineering

---

## Step-by-Step Workflow

### 1. Discover API Endpoints

Run the discovery script against your target site:

```bash
uv run python -m scrapers.discovery "https://www.propertyfinder.eg/en/buy/alexandria/apartments-for-sale.html"
```

This will:
- Launch a stealth Chrome browser via nodriver
- Navigate to the site
- Scroll and interact with the page
- Capture all network traffic
- Save to `data/discovery/propertyfinder.eg_<timestamp>.json`

**Tip:** Use `--headless` for servers, omit it to watch the browser work.

### 2. Filter the Traffic

Run the filter script on the captured data:

```bash
uv run python scripts/filter_traffic.py data/discovery/propertyfinder.eg_20260115_143022.json
```

This will:
- Filter for JSON responses from API-looking URLs
- Score each candidate by relevance
- Show the top 20 most likely listing APIs
- Save filtered results to `data/discovery/filtered_*.json`

### 3. Test the Endpoint

Copy the most promising URL and test it directly:

```bash
curl "https://api.propertyfinder.eg/v1/search?page=1" \
  -H "Accept: application/json" \
  -H "User-Agent: Mozilla/5.0 ..."
```

**If it returns JSON with listing data:** ✅ You found an open API!

**If it returns CAPTCHA/HTML:** ❌ The API is also protected. Try:
- Adding the same headers/cookies from the browser request
- Using a residential proxy provider
- Moving to the next site

### 4. Build the Scraper

Copy the template and fill in your discovered endpoint:

```bash
cp scrapers/api_scraper_template.py scrapers/propertyfinder_api_scraper.py
```

Edit the file:
1. Set `BASE_URL` and `ENDPOINT`
2. Add any required auth headers to `CUSTOM_HEADERS`
3. Customize `_parse_listing()` to match the API response format

### 5. Test & Run

```bash
uv run python -m scrapers.propertyfinder_api_scraper
```

---

## Files

| File | Purpose |
|---|---|
| `scrapers/discovery.py` | Captures network traffic with nodriver |
| `scripts/filter_traffic.py` | Filters captured traffic for API candidates |
| `scrapers/api_scraper_template.py` | Template for building API scrapers |
| `scrapers/api_client.py` | Reusable HTTP client with retries |

---

## Troubleshooting

| Problem | Solution |
|---|---|
| nodriver crashes on startup | Ensure Chrome/Chromium is installed |
| No API candidates found | Try scrolling more, clicking filters, or increasing timeout |
| Endpoint returns 401/403 | Check if it needs auth tokens from browser cookies |
| Endpoint returns HTML instead of JSON | The "API" might be server-rendered. Look for XHR calls with `Accept: application/json` |
| Rate limited (429) | Add delays between requests, use proxy provider, or reduce frequency |

---

## Learning Goals

By completing this workflow, you'll learn:
- ✅ How to intercept network traffic with Chrome DevTools Protocol (CDP)
- ✅ How to identify hidden/internal APIs
- ✅ How to test APIs outside the browser
- ✅ How to build resilient HTTP clients with retries
- ✅ How to map external APIs to your database schema
