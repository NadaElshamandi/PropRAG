"""
Traffic Filter Script

Reads captured network traffic from discovery.py and filters for
potential real estate API endpoints.

Usage:
    uv run python scripts/filter_traffic.py data/discovery/propertyfinder.eg_20260115_143022.json

Output:
    Prints filtered results to stdout
    Optionally saves to data/discovery/filtered_<filename>
"""

import json
import sys
from pathlib import Path

# Keywords that suggest a real estate API response
REAL_ESTATE_KEYWORDS = [
    "price",
    "bedroom",
    "bathroom",
    "area",
    "sqm",
    "location",
    "district",
    "property",
    "listing",
    "apartment",
    "villa",
    "rent",
    "sale",
    "egp",
    "usd",
]

# URL patterns that suggest an API endpoint
API_URL_PATTERNS = [
    "/api/",
    "/graphql",
    "/v1/",
    "/v2/",
    "/search",
    "/listings",
    "/properties",
    "/filter",
    "/query",
]

# Content types we care about
VALID_CONTENT_TYPES = [
    "application/json",
    "application/graphql",
    "text/json",
]


def is_likely_api(request: dict) -> bool:
    """
    Heuristic to determine if a request is likely a real estate API call.
    """
    url = request.get("url", "")
    # Support both old and new field names
    mime_type = request.get("response_mime_type", request.get("content_type", "")).lower()
    status = request.get("response_status", request.get("status", 0))

    # Must be a successful response
    if status != 200:
        return False

    # Must be JSON or similar
    if not any(ct in mime_type for ct in VALID_CONTENT_TYPES):
        return False

    # URL should look like an API
    has_api_pattern = any(pattern in url.lower() for pattern in API_URL_PATTERNS)

    return has_api_pattern


def score_api_relevance(request: dict) -> int:
    """
    Score how likely this API is to contain listing data.
    Higher = more likely.
    """
    score = 0
    url = request.get("url", "").lower()

    # URL patterns (strong signals)
    if "/search" in url or "/listings" in url or "/properties" in url:
        score += 10
    if "/graphql" in url:
        score += 8
    if "/api/" in url:
        score += 5

    # Response size (listing APIs tend to return larger payloads)
    size = request.get("response_size", request.get("body_size", 0))
    if size > 10000:  # 10KB
        score += 5
    elif size > 5000:  # 5KB
        score += 3
    elif size > 1000:  # 1KB
        score += 1

    # Method (GET for search, POST for GraphQL)
    method = request.get("method", "")
    if method == "GET":
        score += 2
    elif method == "POST":
        score += 1  # Could be GraphQL

    # Body content check for real estate keywords
    body = request.get("body_preview", "")
    if body and any(kw in body.lower() for kw in REAL_ESTATE_KEYWORDS):
        score += 3

    return score


def filter_traffic(input_path: str, min_score: int = 5, top_n: int = 20):
    """
    Filter captured traffic for likely real estate APIs.

    Args:
        input_path: Path to discovery JSON file
        min_score: Minimum relevance score to include
        top_n: Maximum number of results to show
    """
    input_file = Path(input_path)
    if not input_file.exists():
        print(f"❌ File not found: {input_path}")
        sys.exit(1)

    print(f"📖 Reading traffic from: {input_path}")
    with open(input_file) as f:
        data = json.load(f)

    # Handle both old 'requests' format and new 'responses' format
    requests = data.get("responses", data.get("requests", []))
    print(f"   Total responses: {len(requests)}")

    # Filter and score
    candidates = []
    for req in requests:
        if is_likely_api(req):
            score = score_api_relevance(req)
            if score >= min_score:
                req["_relevance_score"] = score
                candidates.append(req)

    # Sort by score descending
    candidates.sort(key=lambda x: x["_relevance_score"], reverse=True)

    print(f"   API candidates: {len(candidates)}")
    print()

    if not candidates:
        print("⚠️  No API candidates found. Try lowering min_score or checking the capture.")
        return

    # Display top results
    print("=" * 80)
    print("🎯 TOP REAL ESTATE API CANDIDATES")
    print("=" * 80)
    print()

    for i, req in enumerate(candidates[:top_n], 1):
        print(f"--- Candidate #{i} (score: {req['_relevance_score']}) ---")
        print(f"URL:     {req['url']}")
        print(f"Method:  {req['method']}")
        print(f"Status:  {req.get('response_status', req.get('status', 'unknown'))}")
        print(f"Type:    {req.get('response_mime_type', req.get('content_type', 'unknown'))}")
        print(f"Size:    {req.get('response_size', req.get('body_size', 0))} bytes")
        print()

        # Show request headers (filtered)
        headers = req.get("headers", {})
        interesting_headers = {k: v for k, v in headers.items() if k.lower() in [
            "authorization", "x-api-key", "content-type", "accept"
        ]}
        if interesting_headers:
            print("Headers:")
            for k, v in interesting_headers.items():
                print(f"  {k}: {v}")
            print()

        print()

    # Save filtered results
    output_file = input_file.parent / f"filtered_{input_file.name}"
    with open(output_file, "w") as f:
        json.dump({
            "source": input_path,
            "filtered_at": data.get("captured_at"),
            "total_candidates": len(candidates),
            "candidates": candidates[:top_n],
        }, f, indent=2, default=str)

    print(f"💾 Saved filtered results to: {output_file}")

    # Next steps hint
    print()
    print("=" * 80)
    print("📋 NEXT STEPS")
    print("=" * 80)
    print()
    print("1. Review the URLs above in your browser")
    print("2. Copy the most promising URL")
    print("3. Test it with curl:")
    print(f"   curl '{candidates[0]['url']}' -H 'Accept: application/json'")
    print()
    print("4. If it returns JSON with listing data, build your scraper!")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: uv run python scripts/filter_traffic.py <discovery_json_file>")
        print("Example: uv run python scripts/filter_traffic.py data/discovery/propertyfinder.eg_20260115_143022.json")
        sys.exit(1)

    filter_traffic(sys.argv[1])
