# 🔍 API Discovery Checklist — PropRAG

## Goal
Find hidden API endpoints for PropertyFinder, Aqarmap, and Dubizzle.
Test if they're protected by CAPTCHA or open to direct requests.

---

## Part 1: Browser Recon (30 min per site)

### Step 1: Open DevTools
1. Open Chrome/Edge in **incognito mode** (no cookies, clean state)
2. Navigate to the site
3. Press `F12` → **Network** tab
4. Filter by **Fetch/XHR** (or click "XHR" button)
5. Check "Preserve log" so requests survive page navigation

### Step 2: Trigger API Calls
For each site, do these actions and watch the Network tab:

| Action | What to look for |
|---|---|
| **Load homepage** | Initial data fetch, config, feature flags |
| **Search for "Alexandria apartments"** | Search endpoint, query params |
| **Apply filter: "2 bedrooms"** | Filter params, pagination |
| **Scroll down** | Infinite scroll / "load more" endpoint |
| **Click a listing** | Detail page data fetch |
| **Change sort order** | Sort param in existing endpoint |

### Step 3: Identify the Gold
Look for requests that return **JSON** with listing data. Good signs:
- Response contains `price`, `bedrooms`, `area`, `title`
- Content-Type: `application/json`
- URL contains `/api/`, `/graphql`, `/v1/`, `/listings`, `/search`

**NOT what you want:**
- HTML responses
- CSS/JS/fonts/images
- Analytics/tracking calls (Google Analytics, Facebook Pixel)
- WebSocket connections

### Step 4: Copy the Request
For each promising request, right-click → **Copy** → **Copy as cURL (bash)**

This gives you the exact command with all headers, cookies, and params.

---

## Part 2: Test the Endpoint

### Step 1: Save the cURL
Paste the copied cURL into a terminal. It will look something like:

```bash
curl 'https://www.propertyfinder.eg/api/v1/search' \
  -H 'User-Agent: Mozilla/5.0 ...' \
  -H 'Accept: application/json' \
  -H 'Cookie: session=abc123' \
  --data '{"page":1,"location":"alexandria"}'
```

### Step 2: Strip it down (the real test)
Remove cookies and browser-specific headers. Keep only:
- `User-Agent` (use a normal browser one)
- `Accept: application/json`
- `Content-Type: application/json` (if it's a POST)
- The URL and query params/body

```bash
curl 'https://www.propertyfinder.eg/api/v1/search?page=1&location=alexandria' \
  -H 'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36' \
  -H 'Accept: application/json'
```

### Step 3: Interpret the response

| Response | Meaning | Action |
|---|---|---|
| **JSON with listing data** | ✅ API is OPEN | Build API scraper immediately |
| **HTML with CAPTCHA** | ❌ API is PROTECTED | Need residential proxy |
| **401/403 without CAPTCHA** | ⚠️ API needs AUTH | Find token source (JS, login flow) |
| **404** | ❌ Wrong endpoint | Keep searching |
| **Empty JSON `{}` or `[]`** | ⚠️ Needs specific params | Study the original request more carefully |

---

## Part 3: Document Your Findings

For each site, fill this out:

### PropertyFinder
- [ ] Endpoint URL: `________________`
- [ ] Method: GET / POST
- [ ] Auth required: Yes / No
- [ ] Response format: JSON / HTML
- [ ] CAPTCHA on direct call: Yes / No
- [ ] Pagination: offset / cursor / page number
- [ ] Key fields in response: `price`, `beds`, `baths`, `area`, `title`, `location`

### Aqarmap
- [ ] Endpoint URL: `________________`
- [ ] Method: GET / POST
- [ ] Auth required: Yes / No
- [ ] Response format: JSON / HTML
- [ ] CAPTCHA on direct call: Yes / No
- [ ] Pagination: offset / cursor / page number
- [ ] Key fields in response: `________________`

### Dubizzle
- [ ] Endpoint URL: `________________`
- [ ] Method: GET / POST
- [ ] Auth required: Yes / No
- [ ] Response format: JSON / HTML
- [ ] CAPTCHA on direct call: Yes / No
- [ ] Pagination: offset / cursor / page number
- [ ] Key fields in response: `________________`

---

## Part 4: Quick Python Test Script

Once you have an endpoint, test it with this:

```python
import requests

# Replace with your discovered endpoint
URL = "https://example.com/api/search"
PARAMS = {"page": 1, "location": "alexandria"}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json",
}

r = requests.get(URL, params=PARAMS, headers=HEADERS, timeout=15)
print(f"Status: {r.status_code}")
print(f"Content-Type: {r.headers.get('Content-Type')}")
print(f"First 500 chars:\n{r.text[:500]}")

if r.status_code == 200 and "application/json" in r.headers.get("Content-Type", ""):
    print("\n✅ API is OPEN — build the scraper!")
elif "captcha" in r.text.lower() or "cloudflare" in r.text.lower():
    print("\n❌ CAPTCHA detected — need proxy provider")
else:
    print(f"\n⚠️  Unexpected response — investigate further")
```

---

## Pro Tips

1. **Try the mobile site** — `m.propertyfinder.eg` sometimes has different, less-protected APIs
2. **Check for GraphQL** — if you see `/graphql` in the URL, the request body will have `query` and `variables` fields
3. **Look at the JS bundle** — search for `api/` in the page source to find hardcoded endpoints
4. **Try without JavaScript** — disable JS in Chrome DevTools, reload. If data still loads, it's server-rendered (no API). If it's blank, there's definitely an API.
5. **Check for API documentation** — some sites accidentally leave Swagger/OpenAPI docs at `/api/docs` or `/swagger`
