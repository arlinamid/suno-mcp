"""
Suno Session Manager — JWT lifecycle and Clerk token refresh.

How Suno's auth works (discovered via network interception):
  1. Login creates a Clerk session.  Clerk issues TWO key cookies:
       __client         HTTP-only, long-lived (months), signed client token
                        → used by auth.suno.com to identify the device
       __session        Short-lived JWT (60 min), visible in DevTools
                        → the bearer token sent with every API call
  2. Refresh: POST auth.suno.com/v1/client/sessions/{sid}/tokens
       - Sends __client cookie (HTTP-only, stored internally by Playwright)
       - Response: {"jwt": "<new __session JWT>"}
       - No browser needed once __client is captured

  3. The suffix _Jnxw-muT on __session_Jnxw-muT and __client_uat_Jnxw-muT
     is the Clerk publishable key identifier for suno.com.
     Clerk publishable key: pk_live_Jnxw-muT... (from auth.suno.com/v1/environment)

Strategy:
  - Login once via Playwright → capture ALL cookies (including HTTP-only)
  - Store the full cookie jar in the OS keychain
  - Refresh the __session JWT silently via HTTP before it expires
  - If HTTP refresh fails, fall back to headless browser refresh
"""

import asyncio
import base64
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

CLERK_AUTH_BASE = "https://auth.suno.com"
CLERK_API_VERSION = "2025-11-10"
CLERK_JS_VERSION = "5.117.0"

# Refresh the token if it expires within this many seconds
REFRESH_BUFFER_SECONDS = 300  # 5 minutes


# ── JWT helpers ────────────────────────────────────────────────────────────────

def decode_jwt_payload(token: str) -> Dict[str, Any]:
    """
    Decode a JWT payload without signature verification.

    We only need the claims (expiry, session ID, user info) — not security
    verification, which is the server's job.
    """
    try:
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError("Not a valid JWT (need 3 parts)")
        # Add padding if needed
        payload_b64 = parts[1] + "=="
        payload_bytes = base64.urlsafe_b64decode(payload_b64)
        return json.loads(payload_bytes.decode("utf-8"))
    except Exception as e:
        raise ValueError(f"Failed to decode JWT: {e}") from e


def get_token_expiry(token: str) -> Optional[datetime]:
    """Return the token's expiry datetime (UTC), or None if not parseable."""
    try:
        payload = decode_jwt_payload(token)
        exp = payload.get("exp")
        if exp:
            return datetime.fromtimestamp(exp, tz=timezone.utc)
    except Exception:
        pass
    return None


def get_session_id(token: str) -> Optional[str]:
    """Extract the Clerk session ID from a __session JWT."""
    try:
        return decode_jwt_payload(token).get("sid")
    except Exception:
        return None


def is_token_expired(token: str, buffer_seconds: int = REFRESH_BUFFER_SECONDS) -> bool:
    """
    Return True if the token has expired or will expire within buffer_seconds.

    Uses buffer_seconds=300 (5 min) by default — refresh proactively before
    expiry to avoid mid-request failures.
    """
    expiry = get_token_expiry(token)
    if expiry is None:
        return True  # Unknown expiry → treat as expired
    now = datetime.now(tz=timezone.utc)
    return (expiry - now).total_seconds() < buffer_seconds


def token_claims_summary(token: str) -> str:
    """Return a human-readable non-secret summary of JWT claims."""
    try:
        p = decode_jwt_payload(token)
        exp = datetime.fromtimestamp(p["exp"], tz=timezone.utc)
        iat = datetime.fromtimestamp(p["iat"], tz=timezone.utc)
        now = datetime.now(tz=timezone.utc)
        ttl = (exp - now).total_seconds()
        ttl_str = f"{int(ttl // 60)}m {int(ttl % 60)}s" if ttl > 0 else "EXPIRED"
        return (
            f"Issued   : {iat.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
            f"Expires  : {exp.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
            f"TTL      : {ttl_str}\n"
            f"Session  : {p.get('sid', 'N/A')}\n"
            f"User ID  : {p.get('suno.com/claims/user_id', 'N/A')}\n"
            f"Email    : {p.get('suno.com/claims/email', 'N/A')}\n"
            f"Token type: {p.get('suno.com/claims/token_type', 'N/A')}\n"
            f"Issuer   : {p.get('iss', 'N/A')}"
        )
    except Exception as e:
        return f"Could not decode token: {e}"


# ── Cookie jar helpers ─────────────────────────────────────────────────────────

# Cookies that must be captured after login (from the browser cookie jar)
ESSENTIAL_COOKIES = {
    "__client",           # HTTP-only — the long-lived Clerk client token (KEY for refresh)
    "__session",          # Short-lived JWT (60 min)
    "__client_uat",       # Client update timestamp
    "suno_device_id",     # Suno's persistent device ID
    "has_logged_in_before",
    "clerk_active_context",
    "ssr_bucket",
}

# Cookies with publishable-key-suffixed variants (e.g., __session_Jnxw-muT)
SESSION_COOKIE_PREFIXES = ("__session_", "__client_uat_")


def extract_session_from_cookies(cookie_jar: Dict[str, str]) -> Optional[str]:
    """
    Find the current __session JWT from the cookie jar.
    Prefers the base __session over suffixed variants.
    """
    if "__session" in cookie_jar:
        return cookie_jar["__session"]
    # Fall back to any __session_<suffix> variant
    for name, value in cookie_jar.items():
        if name.startswith("__session_") and value:
            return value
    return None


def build_cookie_header(cookie_jar: Dict[str, str]) -> str:
    """Convert a cookie dict to a Cookie header string."""
    return "; ".join(f"{k}={v}" for k, v in cookie_jar.items())


def cookies_from_playwright(playwright_cookies: List[Dict]) -> Dict[str, str]:
    """
    Convert Playwright's cookie list format to a simple name→value dict.

    Playwright returns: [{"name": "...", "value": "...", "domain": "...", ...}]
    We capture cookies from suno.com and auth.suno.com domains.
    """
    result: Dict[str, str] = {}
    for cookie in playwright_cookies:
        domain = cookie.get("domain", "")
        name = cookie.get("name", "")
        value = cookie.get("value", "")
        if "suno.com" in domain and name and value:
            result[name] = value
    return result


# ── Clerk token refresh ────────────────────────────────────────────────────────

class ClerkTokenRefresher:
    """
    Refreshes the Suno __session JWT using the Clerk authentication API.

    The refresh requires the __client HTTP-only cookie, which can only be
    obtained by running a Playwright browser session during initial login.
    Once captured and stored, it is valid for months.
    """

    def __init__(self) -> None:
        self._client: Optional[httpx.AsyncClient] = None

    def _get_http_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0),
                follow_redirects=True,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/145.0.0.0 Safari/537.36"
                    ),
                    "Origin": "https://suno.com",
                    "Referer": "https://suno.com/",
                    "Accept": "application/json",
                    "__clerk_api_version": CLERK_API_VERSION,
                    "_clerk_js_version": CLERK_JS_VERSION,
                },
            )
        return self._client

    async def refresh_via_http(
        self, session_id: str, cookie_jar: Dict[str, str]
    ) -> Optional[str]:
        """
        Call the Clerk token endpoint directly via HTTP.

        Returns the new JWT string, or None if refresh failed.

        Endpoint: POST https://auth.suno.com/v1/client/sessions/{sid}/tokens
        Requires: __client cookie (long-lived, set by Clerk on login)
        """
        if not session_id:
            logger.error("No session ID — cannot refresh token")
            return None

        client = self._get_http_client()
        url = (
            f"{CLERK_AUTH_BASE}/v1/client/sessions/{session_id}/tokens"
            f"?__clerk_api_version={CLERK_API_VERSION}"
            f"&_clerk_js_version={CLERK_JS_VERSION}"
        )

        try:
            resp = await client.post(
                url,
                content=b"",  # empty body
                headers={
                    "Cookie": build_cookie_header(cookie_jar),
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )

            if resp.status_code == 200:
                data = resp.json()
                new_jwt = data.get("jwt") or data.get("object")
                if new_jwt and "." in str(new_jwt):
                    logger.info("Token refreshed successfully via Clerk HTTP API")
                    return str(new_jwt)
                # Some Clerk versions return it nested
                if isinstance(data.get("response"), dict):
                    new_jwt = data["response"].get("jwt")
                    if new_jwt:
                        return str(new_jwt)
                logger.warning("Refresh response had unexpected shape: %s", list(data.keys()))
            else:
                body = resp.text[:200]
                logger.warning(
                    "Clerk token refresh HTTP %d: %s", resp.status_code, body
                )
        except Exception as e:
            logger.error("HTTP token refresh failed: %s", e)

        return None

    async def refresh_via_playwright(self, cookie_jar: Dict[str, str]) -> Optional[str]:
        """
        Fallback: launch a headless browser with the stored cookies,
        navigate to suno.com, and let Clerk's JS SDK refresh the token.

        Returns the new __session JWT from the browser's cookie jar.
        """
        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/145.0.0.0 Safari/537.36"
                    )
                )

                # Inject stored cookies into the browser context
                playwright_cookies = [
                    {
                        "name": name,
                        "value": value,
                        "domain": ".suno.com",
                        "path": "/",
                        "secure": True,
                        "httpOnly": name.startswith("__client"),
                        "sameSite": "Lax",
                    }
                    for name, value in cookie_jar.items()
                ]
                await context.add_cookies(playwright_cookies)

                page = await context.new_page()

                # Navigate to suno.com — Clerk's JS SDK will auto-refresh the token
                await page.goto("https://suno.com/home", wait_until="networkidle")
                await asyncio.sleep(3)  # Allow Clerk to complete refresh

                # Extract all cookies including the refreshed __session
                all_cookies = await context.cookies()
                new_jar = cookies_from_playwright(all_cookies)

                await browser.close()

                new_session = extract_session_from_cookies(new_jar)
                if new_session and not is_token_expired(new_session, buffer_seconds=0):
                    logger.info("Token refreshed via Playwright fallback")
                    return new_session, new_jar  # type: ignore[return-value]

        except Exception as e:
            logger.error("Playwright token refresh failed: %s", e)

        return None

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()


# Module-level singleton
_refresher: Optional[ClerkTokenRefresher] = None


def get_refresher() -> ClerkTokenRefresher:
    global _refresher
    if _refresher is None:
        _refresher = ClerkTokenRefresher()
    return _refresher
