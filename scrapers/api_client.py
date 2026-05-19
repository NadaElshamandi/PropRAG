"""
api_client.py
-------------
Production-ready HTTP client module for API-based data extraction.
Demonstrates three approaches:

    1. Hidden API (reverse-engineered internal endpoints)
    2. Proxy API (ScraperAPI / ScrapingBee / ZenRows)
    3. Reliability layer (exponential backoff, HTTP error handling)

Usage:
    from scrapers.api_client import HiddenAPIClient, ProxyAPIClient

    # Approach 1 — Hidden API
    client = HiddenAPIClient(
        base_url="https://internal-api.example.com",
        bearer_token="your-token-here",
    )
    data = client.get_listings(page=1)

    # Approach 2 — Proxy API
    proxy = ProxyAPIClient(
        proxy_provider="zenrows",  # or "scraperapi", "scrapingbee"
        api_key="your-proxy-key",
    )
    html = proxy.fetch("https://example.com/listings")

Environment variables (recommended for secrets):
    PROXY_API_KEY=your-key-here
    HIDDEN_API_TOKEN=your-token-here
"""

import logging
from typing import Any, Optional

import requests
from requests.adapters import HTTPAdapter
from requests.exceptions import JSONDecodeError, RequestException
from urllib3.util.retry import Retry

logger = logging.getLogger("api_client")


# ── 3. RELIABILITY LAYER ────────────────────────────────────────────────────

class ReliabilityMixin:
    """
    Mixin that wraps any HTTP session with:
        - Connection pooling (keep-alive)
        - Exponential-backoff retries on 429 / 5xx
        - Custom adapter with tuned timeouts
    """

    def _build_session(
        self,
        *,
        max_retries: int = 3,
        backoff_factor: float = 1.0,
        status_forcelist: tuple[int, ...] = (429, 500, 502, 503, 504),
        pool_connections: int = 10,
        pool_maxsize: int = 10,
    ) -> requests.Session:
        """
        Create a requests.Session with reliability tuning.

        Args:
            max_retries:      Total retry attempts for transient failures.
            backoff_factor:   Sleep = {backoff_factor} * (2 ** (retry - 1)) seconds.
                              1.0 → 1s, 2s, 4s, ... between retries.
            status_forcelist: HTTP status codes that trigger a retry.
            pool_connections: Size of the connection pool (one per host).
            pool_maxsize:     Max queued connections in the pool.
        """
        session = requests.Session()

        # --- Retry strategy ---
        # urllib3's Retry handles 429 (rate-limit) and 5xx automatically.
        # It respects the `Retry-After` header when present.
        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=backoff_factor,
            status_forcelist=status_forcelist,
            allowed_methods=["HEAD", "GET", "POST"],  # safe to retry
            raise_on_status=False,
        )

        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=pool_connections,
            pool_maxsize=pool_maxsize,
        )

        session.mount("https://", adapter)
        session.mount("http://", adapter)

        return session


# ── 1. HIDDEN API APPROACH ──────────────────────────────────────────────────

class HiddenAPIClient(ReliabilityMixin):
    """
    Client for reverse-engineered internal JSON endpoints.

    Mimics a real browser by sending:
        - Standard Accept headers (tells server we want JSON)
        - Referer (makes the request look like it came from the site)
        - X-Requested-With: XMLHttpRequest (marks it as an AJAX call)
        - Auth token (Bearer or API-key header)
        - Session cookies (if the endpoint requires login state)
    """

    def __init__(
        self,
        base_url: str,
        *,
        bearer_token: Optional[str] = None,
        api_key_header: Optional[tuple[str, str]] = None,
        cookies: Optional[dict[str, str]] = None,
        referer: Optional[str] = None,
        timeout: float = 30.0,
    ):
        """
        Args:
            base_url:        Root URL of the hidden API (no trailing slash).
            bearer_token:    JWT / OAuth token for Authorization header.
            api_key_header:  Tuple of (header_name, key_value) if the API uses
                             a custom header like X-API-Key instead of Bearer.
            cookies:         Dict of session cookies (e.g., {"sessionid": "abc"}).
            referer:         Page the request supposedly came from.
            timeout:         Seconds before giving up on a single request.
        """
        self.base_url = base_url.rstrip("/")
        self.bearer_token = bearer_token
        self.api_key_header = api_key_header
        self.timeout = timeout

        self.session = self._build_session()

        # --- Standard browser-like headers ---
        # These headers make the request look like it came from a real browser
        # navigating the site, not a headless scraper.
        default_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/133.0.0.0 Safari/537.36"
            ),
            "Accept": (
                "application/json, text/plain, */*"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
        }

        if referer:
            default_headers["Referer"] = referer

        # X-Requested-With signals an AJAX/Fetch request — many internal APIs
        # block requests that lack this header (they assume it's a direct bot).
        default_headers["X-Requested-With"] = "XMLHttpRequest"

        self.session.headers.update(default_headers)

        # --- Authentication headers ---
        if bearer_token:
            # Standard OAuth 2.0 Bearer token pattern
            self.session.headers["Authorization"] = f"Bearer {bearer_token}"

        if api_key_header:
            header_name, key_value = api_key_header
            self.session.headers[header_name] = key_value

        # --- Session cookies ---
        if cookies:
            # Cookies preserve login state, CSRF tokens, or device fingerprints.
            # If the server sets cookies during a normal browser visit, copy them
            # from the Network tab → Request Headers → cookie field.
            self.session.cookies.update(cookies)

    # ── Public API ────────────────────────────────────────────────────────────

    def get_listings(self, page: int = 1) -> list[dict]:
        """
        Example endpoint: GET /api/v1/listings?page={page}
        Returns parsed JSON or an empty list on any error.
        """
        url = f"{self.base_url}/api/v1/listings"
        params = {"page": page}

        try:
            response = self.session.get(
                url,
                params=params,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return self._safe_json(response)

        except requests.HTTPError as e:
            status = e.response.status_code if e.response else "?"
            if status in (401, 403):
                logger.error(
                    f"Auth failure ({status}): token expired or insufficient "
                    f"scope. Check your Bearer token / API key."
                )
            else:
                logger.error(f"HTTP error {status} from hidden API: {e}")
            return []

        except RequestException as e:
            logger.error(f"Network failure calling hidden API: {e}")
            return []

    def _safe_json(self, response: requests.Response) -> Any:
        """
        Parse JSON safely. If the server returns HTML (e.g., a Cloudflare
        block page), catch the decode error and return an empty structure.
        """
        try:
            return response.json()
        except JSONDecodeError:
            # Log a preview so we know what the server actually sent
            preview = response.text[:200].replace("\n", " ")
            logger.warning(
                f"Expected JSON but got HTML/text. Preview: {preview}..."
            )
            return []


# ── 2. PROXY / SCRAPER API APPROACH ─────────────────────────────────────────

class ProxyAPIClient(ReliabilityMixin):
    """
    Routes requests through a third-party proxy/scraper service.

    Supported providers: "zenrows", "scraperapi", "scrapingbee".
    The provider handles:
        - Residential IP rotation (bypasses rate limits)
        - JavaScript rendering (if using premium tier)
        - CAPTCHA solving (on supported tiers)
        - Geographic IP targeting
    """

    PROVIDER_URLS: dict[str, str] = {
        # ZenRows: pass target URL as ?url=... and API key as ?apikey=...
        "zenrows": "https://api.zenrows.com/v1/",

        # ScraperAPI: pass target URL as ?url=... and key as &api_key=...
        "scraperapi": "http://api.scraperapi.com/",

        # ScrapingBee: target URL is the path after the API key
        "scrapingbee": "https://app.scrapingbee.com/api/v1/",
    }

    def __init__(
        self,
        proxy_provider: str,
        api_key: str,
        *,
        render_js: bool = False,
        premium_proxy: bool = False,
        country_code: Optional[str] = None,
        timeout: float = 60.0,
    ):
        """
        Args:
            proxy_provider:   One of "zenrows", "scraperapi", "scrapingbee".
            api_key:          Your proxy-service API key.
            render_js:        Ask the proxy to execute JavaScript (slower,
                              but needed for SPA / React sites).
            premium_proxy:    Use residential / mobile IPs (harder to block).
            country_code:     Geo-targeting, e.g., "EG" for Egypt.
            timeout:          Proxy services are slower; allow more time.
        """
        if proxy_provider not in self.PROVIDER_URLS:
            raise ValueError(
                f"Unknown provider '{proxy_provider}'. "
                f"Choose from: {list(self.PROVIDER_URLS.keys())}"
            )

        self.provider = proxy_provider
        self.api_key = api_key
        self.render_js = render_js
        self.premium_proxy = premium_proxy
        self.country_code = country_code
        self.timeout = timeout

        self.session = self._build_session(
            # Proxies are slower; be more patient with retries
            max_retries=5,
            backoff_factor=2.0,
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def fetch(self, target_url: str) -> Optional[str]:
        """
        Fetch a target URL through the proxy provider.
        Returns raw response text (HTML or JSON) or None on failure.
        """
        proxy_url, proxy_params = self._build_proxy_request(target_url)

        try:
            response = self.session.get(
                proxy_url,
                params=proxy_params,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.text

        except requests.HTTPError as e:
            status = e.response.status_code if e.response else "?"
            if status == 401:
                logger.error(
                    "Proxy API returned 401: your API key is invalid or "
                    "you have exceeded your plan limits."
                )
            elif status == 429:
                logger.error(
                    "Proxy API returned 429: you have exceeded the "
                    "request rate for your plan. Upgrade or slow down."
                )
            else:
                logger.error(f"Proxy API HTTP error {status}: {e}")
            return None

        except RequestException as e:
            logger.error(f"Network failure calling proxy API: {e}")
            return None

    def fetch_json(self, target_url: str) -> Any:
        """
        Convenience wrapper that parses the proxy response as JSON.
        Returns [] on failure so callers don't crash.
        """
        text = self.fetch(target_url)
        if text is None:
            return []

        try:
            return self.session.get(target_url).json()
        except JSONDecodeError:
            preview = text[:200].replace("\n", " ")
            logger.warning(
                f"Expected JSON from proxy but got HTML/text. Preview: {preview}..."
            )
            return []

    # ── Internal helpers ────────────────────────────────────────────────────

    def _build_proxy_request(self, target_url: str) -> tuple[str, dict]:
        """
        Build the proxy URL and parameters for the chosen provider.
        Each provider has a different query-param contract.
        """
        base = self.PROVIDER_URLS[self.provider]

        if self.provider == "zenrows":
            # ZenRows: ?apikey=<key>&url=<target>
            # Optional: &js_render=true, &premium_proxy=true, &country=<cc>
            params: dict[str, Any] = {
                "apikey": self.api_key,
                "url": target_url,
            }
            if self.render_js:
                params["js_render"] = "true"
            if self.premium_proxy:
                params["premium_proxy"] = "true"
            if self.country_code:
                params["country"] = self.country_code
            return base, params

        if self.provider == "scraperapi":
            # ScraperAPI: ?api_key=<key>&url=<target>
            # Optional: &render=true, &premium=true, &country_code=<cc>
            params = {
                "api_key": self.api_key,
                "url": target_url,
            }
            if self.render_js:
                params["render"] = "true"
            if self.premium_proxy:
                params["premium"] = "true"
            if self.country_code:
                params["country_code"] = self.country_code
            return base, params

        if self.provider == "scrapingbee":
            # ScrapingBee: ?api_key=<key>&url=<target>
            # Optional: &render_js=true, &premium_proxy=true, &country=<cc>
            params = {
                "api_key": self.api_key,
                "url": target_url,
            }
            if self.render_js:
                params["render_js"] = "true"
            if self.premium_proxy:
                params["premium_proxy"] = "true"
            if self.country_code:
                params["country_code"] = self.country_code
            return base, params

        # Should never reach here because __init__ validates the provider
        raise RuntimeError(f"Unhandled provider: {self.provider}")


# ── DEMO / SELF-TEST ────────────────────────────────────────────────────────

def _demo():
    """
    Quick sanity check — runs against httpbin.org (safe public test API).
    Run with: uv run python -m scrapers.api_client
    """
    print("=" * 60)
    print("1. HIDDEN API CLIENT DEMO")
    print("=" * 60)

    hidden = HiddenAPIClient(
        base_url="https://httpbin.org",
        bearer_token="demo-token-123",
        referer="https://example.com/listings",
        cookies={"sessionid": "abc123"},
    )
    # httpbin /bearer endpoint echoes the Authorization header back
    try:
        r = hidden.session.get(
            "https://httpbin.org/bearer",
            headers={"Authorization": "Bearer demo-token-123"},
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            print(f"   Auth header echoed back: {data.get('token', 'N/A')}")
        else:
            print(f"   httpbin returned {r.status_code}")
    except Exception as e:
        print(f"   Error: {e}")

    print()
    print("=" * 60)
    print("2. PROXY API CLIENT DEMO")
    print("=" * 60)

    proxy = ProxyAPIClient(
        proxy_provider="zenrows",
        api_key="demo-key-456",
        render_js=False,
        premium_proxy=False,
    )
    # Build the request without actually calling the proxy (would need real key)
    url, params = proxy._build_proxy_request("https://example.com/listings?page=1")
    print(f"   Provider base URL: {url}")
    print(f"   Query params:    {params}")

    print()
    print("=" * 60)
    print("3. RELIABILITY LAYER — Retry config")
    print("=" * 60)
    adapter = hidden.session.get_adapter("https://")
    retry = adapter.max_retries  # type: ignore[attr-defined]
    print(f"   Total retries:        {retry.total}")
    print(f"   Backoff factor:       {retry.backoff_factor}")
    print(f"   Status force-list:    {retry.status_forcelist}")
    print(f"   Allowed methods:      {retry.allowed_methods}")
    print()
    print("All demos complete.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    _demo()
