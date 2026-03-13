"""
API-based Suno tools — direct HTTP calls + browser login with auto-refresh.

Endpoints discovered via network interception on suno.com:
  Base URL  : https://studio-api.prod.suno.com/api
  Auth URL  : https://auth.suno.com/v1  (Clerk)

Recommended authentication:
  Use suno_browser_login() — opens a browser window, waits for you to log in,
  then captures ALL session cookies (including the HTTP-only __client token).
  The MCP will then silently refresh your JWT every 60 minutes automatically.

Fallback (manual):
  Set SUNO_COOKIE env var with the __session Clerk cookie from your browser
  (DevTools > Application > Cookies > suno.com > __session value).
  Note: Manual cookie requires re-setting every 60 minutes.
"""

import asyncio
import json
import logging
import os
import pathlib
import re
from typing import Any, Dict, List, Optional

from ..shared.api_client import SunoApiClient, get_api_client
from ..shared.credentials import get_credential_store
from ..shared.exceptions import SunoError
from ..shared.session_manager import (
    get_refresher,
    is_token_expired,
    token_claims_summary,
    cookies_from_playwright,
)


def _fmt_clip(clip: Dict[str, Any], verbose: bool = False) -> str:
    """Format a clip object into a readable string."""
    meta = clip.get("metadata", {}) or {}
    lines = [
        f"🎵 **{clip.get('title', 'Untitled')}**",
        f"   ID       : {clip.get('id', 'N/A')}",
        f"   By       : {clip.get('display_name', '?')} (@{clip.get('handle', '?')})",
        f"   Duration : {round(meta.get('duration', 0))}s",
        f"   Tags     : {meta.get('tags', 'N/A')}",
        f"   Plays    : {clip.get('play_count', 0):,}",
        f"   Likes    : {clip.get('upvote_count', 0):,}",
        f"   Public   : {clip.get('is_public', False)}",
        f"   Model    : {clip.get('model_name', clip.get('major_model_version', 'N/A'))}",
        f"   Audio    : {clip.get('audio_url', 'N/A')}",
    ]
    if verbose:
        lines += [
            f"   Image    : {clip.get('image_url', 'N/A')}",
            f"   Video    : {clip.get('video_url', 'N/A')}",
            f"   Created  : {clip.get('created_at', 'N/A')}",
            f"   Status   : {clip.get('status', 'N/A')}",
            f"   Prompt   : {meta.get('prompt', 'N/A')}",
        ]
    return "\n".join(lines)


def _auth_status(client: SunoApiClient) -> str:
    if client.is_authenticated():
        return "Authenticated"
    return (
        "Not authenticated. Run suno_browser_login() to log in.\n"
        "The MCP will then automatically refresh your session."
    )


class ApiSunoTools:
    """API-based Suno tools — all HTTP, no browser automation."""

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)

    # ── Browser login (captures full cookie jar with HTTP-only __client) ──────

    async def browser_login(self, headless: bool = False, timeout: int = 120) -> str:
        """
        Open a Chromium browser window, wait for the user to log into suno.com,
        then automatically capture ALL session cookies — including the HTTP-only
        __client Clerk token that enables silent JWT refresh.

        After this login:
          • The __session JWT is refreshed automatically every 60 minutes
          • No manual re-login needed until the Clerk session expires (months)
          • Uses Clerk HTTP API for fast refresh (no browser required)
          • Falls back to headless browser if HTTP refresh fails

        Args:
            headless: If True, run without a visible browser window (for environments
                      where you can inject cookies manually).
            timeout:  Seconds to wait for the user to complete login (default: 120).

        Returns:
            Session info and confirmation of what was captured.
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return (
                "Playwright not installed. Run: pip install playwright && playwright install chromium\n"
                "Then retry suno_browser_login()."
            )

        creds = get_credential_store()

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=headless,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/145.0.0.0 Safari/537.36"
                )
            )

            # Pre-load any existing cookies so the user might be auto-logged in
            existing_jar = creds.get_cookie_jar()
            if existing_jar:
                playwright_cookies = []
                for name, value in existing_jar.items():
                    playwright_cookies.append({
                        "name": name, "value": value,
                        "domain": ".suno.com", "path": "/",
                        "secure": True,
                        "httpOnly": name in ("__client",),
                        "sameSite": "Lax",
                    })
                await context.add_cookies(playwright_cookies)

            page = await context.new_page()
            await page.goto("https://suno.com/home", wait_until="domcontentloaded")

            # Wait until the user is logged in (the /api/session endpoint returns a user)
            logged_in = False
            deadline = asyncio.get_event_loop().time() + timeout
            while asyncio.get_event_loop().time() < deadline:
                try:
                    cookies = await context.cookies()
                    jar = cookies_from_playwright(cookies)
                    # Check for a valid __session JWT that contains a user ID
                    session_tok = jar.get("__session") or next(
                        (v for k, v in jar.items() if k.startswith("__session_")), None
                    )
                    if session_tok and "." in session_tok:
                        import base64
                        try:
                            payload = json.loads(
                                base64.urlsafe_b64decode(session_tok.split(".")[1] + "==")
                            )
                            if payload.get("suno.com/claims/user_id"):
                                logged_in = True
                                break
                        except Exception:
                            pass
                except Exception:
                    pass
                await asyncio.sleep(2)

            if not logged_in:
                await browser.close()
                return (
                    f"Login timed out after {timeout}s. "
                    "Please run suno_browser_login() again and complete the sign-in within the time limit."
                )

            # Capture ALL cookies (including HTTP-only __client)
            all_cookies = await context.cookies(["https://suno.com", "https://auth.suno.com"])
            await browser.close()

        jar = cookies_from_playwright(all_cookies)
        if not jar:
            return "No suno.com cookies captured. Did the login succeed?"

        # Save to secure keychain
        result = creds.save_cookie_jar(jar)
        return f"Login successful!\n\n{result}"

    # ── Token refresh ─────────────────────────────────────────────────────────

    async def refresh_session(self, force: bool = False) -> str:
        """
        Silently refresh the __session JWT token without requiring re-login.

        The MCP calls this automatically before API requests when the token is
        about to expire. Use this tool to trigger a manual refresh or to check
        if refresh is working correctly.

        Strategy:
          1. POST to auth.suno.com/v1/client/sessions/{id}/tokens (HTTP, fast)
             — requires the __client cookie captured during browser_login
          2. Headless browser fallback if HTTP fails

        Args:
            force: Refresh even if the current token is still valid.

        Returns:
            Refresh outcome and new token info.
        """
        creds = get_credential_store()
        current_jwt = creds.get_current_jwt()

        if not current_jwt:
            return (
                "No session token found. Run suno_browser_login() first."
            )

        if not force and not is_token_expired(current_jwt):
            return (
                f"Token is still valid — no refresh needed.\n\n"
                f"{token_claims_summary(current_jwt)}\n\n"
                f"Use force=True to refresh anyway."
            )

        session_id = creds.get_session_id()
        jar = creds.get_cookie_jar()

        if not session_id:
            return (
                "No session ID stored. The session may be from a manual cookie paste.\n"
                "Run suno_browser_login() for full automatic refresh support."
            )

        refresher = get_refresher()

        # Strategy 1: Clerk HTTP API
        if jar and "__client" in jar:
            new_jwt = await refresher.refresh_via_http(session_id, jar)
            if new_jwt:
                creds.update_session_token(new_jwt)
                return (
                    f"Token refreshed via Clerk HTTP API\n\n"
                    f"{token_claims_summary(new_jwt)}"
                )

        # Strategy 2: Playwright fallback
        if jar:
            result = await refresher.refresh_via_playwright(jar)
            if result:
                new_jwt, new_jar = result  # type: ignore[misc]
                creds.update_session_token(new_jwt, updated_jar=new_jar)
                return (
                    f"Token refreshed via browser fallback\n\n"
                    f"{token_claims_summary(new_jwt)}"
                )

        return (
            "Token refresh failed.\n"
            "The __client cookie may have expired (this happens after months of inactivity).\n"
            "Run suno_browser_login() to re-authenticate."
        )

    # ── Session info ──────────────────────────────────────────────────────────

    async def session_info(self) -> str:
        """
        Show current session status: token validity, expiry, user info,
        and whether auto-refresh is available.

        Returns a non-secret summary (no tokens or cookies are revealed).
        """
        creds = get_credential_store()
        return creds.status()

    # ── Auth helper ──────────────────────────────────────────────────────────

    async def set_auth_token(self, token: str) -> str:
        """Store an auth token for API calls (called after browser login)."""
        client = get_api_client()
        client.set_session_token(token)
        return "Auth token stored. API calls will now be authenticated."

    async def check_auth(self) -> str:
        """Check authentication status and test the API connection."""
        client = get_api_client()
        status = _auth_status(client)

        if client.is_authenticated():
            try:
                session = await client.get_session()
                user = session.get("user", session)
                display = user.get("display_name") or user.get("handle") or "Unknown"
                return (
                    f"{status}\n"
                    f"   User: {display}\n"
                    f"   Session: Active\n"
                    f"\n✅ API connection successful!"
                )
            except SunoError as e:
                if "AUTH_REQUIRED" in str(e.code if hasattr(e, 'code') else ''):
                    return f"❌ Token invalid or expired.\n{_auth_status(get_api_client())}"
                return f"✅ Token set, but session check failed: {e}\n(Token may still work for generation)"
        return status

    # ── Credits & Billing ───────────────────────────────────────────────────

    async def get_credits(self) -> str:
        """Get remaining credits and subscription info."""
        client = get_api_client()
        try:
            data = await client.get_credits()
            total = data.get("total_credits_left", data.get("credits", {}).get("total", "N/A"))
            monthly = data.get("monthly_limit", "N/A")
            used = data.get("used_credits", "N/A")
            plan = data.get("subscription_type", data.get("plan", "N/A"))
            return (
                f"💳 **Credits & Subscription**\n"
                f"   Plan          : {plan}\n"
                f"   Credits Left  : {total}\n"
                f"   Monthly Limit : {monthly}\n"
                f"   Used          : {used}\n"
                f"\nFull response: {json.dumps(data, indent=2)[:500]}"
            )
        except SunoError:
            raise

    async def get_billing_info(self) -> str:
        """Get full billing and subscription details."""
        client = get_api_client()
        data = await client.get_billing_info()
        return f"💳 **Billing Info**\n\n{json.dumps(data, indent=2)[:1000]}"

    async def get_subscription_plans(self) -> str:
        """Get all available Suno subscription plans (public, no auth needed)."""
        client = get_api_client()
        data = await client.get_billing_plans()
        plans = data.get("plans", [])
        lines = ["📦 **Suno Subscription Plans**\n"]
        for plan in plans:
            lines.append(
                f"• **{plan.get('name', '?')}** — "
                f"${plan.get('price', '?')}/mo | "
                f"{plan.get('credits', '?')} credits/mo | "
                f"{plan.get('description', '')}"
            )
        return "\n".join(lines)

    # ── Song Discovery (Public) ──────────────────────────────────────────────

    async def get_trending_songs(self, page: int = 0, period: str = "") -> str:
        """
        Get trending songs (public, no auth needed).

        Args:
            page: Page number (0-based)
            period: Time period — '' (all-time), 'week', 'day'
        """
        client = get_api_client()
        data = await client.get_trending(page=page, period=period or None)
        clips = data.get("playlist_clips", [])
        total = data.get("num_total_results", len(clips))
        period_label = period or "all-time"

        lines = [f"🔥 **Trending Songs** ({period_label}) — {total} total\n"]
        for item in clips[:20]:
            clip = item.get("clip", item)
            meta = clip.get("metadata", {}) or {}
            lines.append(
                f"• [{clip.get('upvote_count', 0):,}❤️] **{clip.get('title', '?')}** "
                f"by @{clip.get('handle', '?')} | "
                f"{round(meta.get('duration', 0))}s | "
                f"{meta.get('tags', '')[:50]}\n"
                f"  ID: {clip.get('id', '?')}"
            )
        lines.append(f"\nShowing {len(clips)} of {total}. Use page={page + 1} for more.")
        return "\n".join(lines)

    async def get_song(self, song_id: str) -> str:
        """
        Get detailed info about a specific song by ID.

        Args:
            song_id: The song/clip UUID (from trending, search, or your library)
        """
        client = get_api_client()
        clip = await client.get_clip(song_id)
        return _fmt_clip(clip, verbose=True)

    async def search_songs(
        self,
        query: str,
        search_type: str = "audio",
        page: int = 0,
    ) -> str:
        """
        Search for songs, users, or playlists.

        Args:
            query: Search term
            search_type: 'audio' | 'playlist' | 'user'
            page: Page number (0-based)
        """
        client = get_api_client()
        data = await client.search_songs(query, search_type=search_type, page=page)
        result = data.get("result", {})

        if not result:
            return f"🔍 No results found for '{query}'"

        lines = [f"🔍 **Search: '{query}'** ({search_type})\n"]
        clips = result.get("clips", [])
        for clip in clips[:20]:
            meta = clip.get("metadata", {}) or {}
            lines.append(
                f"• **{clip.get('title', '?')}** by @{clip.get('handle', '?')} | "
                f"{round(meta.get('duration', 0))}s | "
                f"{clip.get('upvote_count', 0):,}❤️\n"
                f"  ID: {clip.get('id', '?')} | Tags: {meta.get('tags', '')[:60]}"
            )

        users = result.get("users", [])
        for user in users[:5]:
            lines.append(f"👤 @{user.get('handle', '?')} — {user.get('display_name', '?')}")

        if not clips and not users:
            lines.append(f"Raw result: {json.dumps(result, indent=2)[:400]}")

        return "\n".join(lines)

    async def get_playlist(self, playlist_id: str, page: int = 0) -> str:
        """
        Get a public playlist by ID.

        Args:
            playlist_id: The playlist UUID
            page: Page number (0-based)
        """
        client = get_api_client()
        data = await client.get_playlist(playlist_id, page=page)
        clips = data.get("playlist_clips", [])
        total = data.get("num_total_results", len(clips))
        name = data.get("name", "Unknown")
        by = data.get("user_handle", "?")
        desc = data.get("description", "")

        lines = [
            f"📋 **Playlist: {name}**",
            f"   By      : @{by}",
            f"   Songs   : {total}",
            f"   Desc    : {desc[:100]}",
            f"   Public  : {data.get('is_public', False)}\n",
        ]
        for item in clips[:20]:
            clip = item.get("clip", item)
            meta = clip.get("metadata", {}) or {}
            lines.append(
                f"• **{clip.get('title', '?')}** by @{clip.get('handle', '?')} | "
                f"{round(meta.get('duration', 0))}s | ID: {clip.get('id', '?')}"
            )
        lines.append(f"\nShowing {len(clips)} of {total}.")
        return "\n".join(lines)

    # ── User Library (Authenticated) ─────────────────────────────────────────

    async def get_my_songs(self, page: int = 0) -> str:
        """Get your own generated songs (requires auth)."""
        client = get_api_client()
        data = await client.get_feed(page=page)
        # API may return a list directly or {"clips": [...], "num_total_results": N}
        if isinstance(data, list):
            clips, total = data, len(data)
        else:
            clips = data.get("clips", [])
            total = data.get("num_total_results", len(clips))

        lines = [f"🎵 **My Songs** (page {page + 1}) — {total} total\n"]
        for clip in clips[:20]:
            meta = clip.get("metadata", {}) or {}
            lines.append(
                f"• [{clip.get('status', '?')}] **{clip.get('title', '?')}** | "
                f"{round(meta.get('duration', 0))}s | "
                f"{meta.get('tags', '')[:50]}\n"
                f"  ID: {clip.get('id', '?')}"
            )
        lines.append(f"\nShowing {len(clips)} of {total}. Use page={page + 1} for more.")
        return "\n".join(lines)

    async def get_my_playlists(self, page: int = 0) -> str:
        """Get your own playlists (requires auth)."""
        client = get_api_client()
        data = await client.get_user_playlists(page=page)
        playlists = data if isinstance(data, list) else data.get("playlists", [])

        lines = [f"📋 **My Playlists**\n"]
        for pl in playlists:
            lines.append(
                f"• **{pl.get('name', '?')}** | {pl.get('song_count', 0)} songs | "
                f"ID: {pl.get('id', '?')}"
            )
        return "\n".join(lines) if lines[1:] else "📋 No playlists found."

    # ── Music Generation (Authenticated) ────────────────────────────────────

    # Model display name → API mv value
    SUNO_MODELS: Dict[str, str] = {
        # v5
        "v5":        "chirp-crow",
        "v5-pro":    "chirp-crow",
        "chirp-crow": "chirp-crow",
        # v4.5
        "v4.5x":     "chirp-bluejay",
        "v4.5x-pro": "chirp-bluejay",
        "chirp-bluejay": "chirp-bluejay",
        "v4.5":      "chirp-auk",
        "v4.5-pro":  "chirp-auk",
        "chirp-auk": "chirp-auk",
        "v4.5-all":  "chirp-v4-5",
        "chirp-v4-5": "chirp-v4-5",
        # v4
        "v4":        "chirp-v4",
        "v4-pro":    "chirp-v4",
        "chirp-v4":  "chirp-v4",
        # v3.5
        "v3.5":      "chirp-v3-5",
        "chirp-v3-5": "chirp-v3-5",
        # v3
        "v3":        "chirp-v3-0",
        "chirp-v3":  "chirp-v3-0",
    }

    async def api_generate_track(
        self,
        prompt: str,
        tags: str = "",
        title: str = "",
        make_instrumental: bool = False,
        model: str = "v5",
        # Advanced options
        negative_tags: str = "",
        vocal_gender: str = "",
        weirdness: int = 50,
        style_weight: int = 50,
    ) -> str:
        """
        Generate a new song via direct API call — supports all Suno advanced options.

        Models (use short name or full API name):
          v5 / chirp-crow      — v5 Pro (best quality, default)
          v4.5x / chirp-bluejay— v4.5x Pro (advanced creation)
          v4.5 / chirp-auk     — v4.5 Pro (intelligent prompts)
          v4.5-all / chirp-v4-5— v4.5 all (best free model)
          v4 / chirp-v4        — v4 Pro
          v3.5 / chirp-v3-5    — v3.5
          v3 / chirp-v3        — v3

        Args:
            prompt: Lyrics (with [Verse]/[Chorus] tags) OR description for auto mode.
                    Leave blank with make_instrumental=True for a pure instrumental.
            tags: Style tags separated by commas
                  e.g. "Hungarian rap, 90 BPM, cinematic, male vocals, dark"
            title: Song title (optional)
            make_instrumental: True = no vocals, instrumental only
            model: Model version (default: 'v5')
            negative_tags: Styles/sounds to explicitly avoid
                           e.g. "auto-tune, trap hi-hats, electric guitar"
            vocal_gender: "male", "female", or "" (auto)
            weirdness: 0–100 — how experimental/unexpected (default: 50)
            style_weight: 0–100 — how strongly style tags are applied (default: 50)

        Returns:
            Clip IDs + status to poll with suno_api_wait_for_song() or suno_api_download_song()

        Cost: 10 credits per song × 2 variations = 20 credits per call
        """
        # Resolve model alias → API mv string
        mv = self.SUNO_MODELS.get(model, model)

        data = await self._generate_via_browser(
            prompt=prompt,
            tags=tags,
            title=title,
            make_instrumental=make_instrumental,
            mv=mv,
            negative_tags=negative_tags,
            vocal_gender=vocal_gender if vocal_gender in ("male", "female") else None,
            weirdness=weirdness,
            style_weight=style_weight,
        )

        clips = data.get("clips", [])
        if not clips:
            return f"🎵 Generation started!\nResponse: {json.dumps(data, indent=2)[:600]}"

        lines = [f"🎵 **Generation Started!** ({len(clips)} clips) — model: {mv}\n"]
        for clip in clips:
            lines.append(
                f"• **{clip.get('title', title or prompt[:30])}**\n"
                f"  ID     : {clip.get('id', '?')}\n"
                f"  Status : {clip.get('status', 'queued')}\n"
                f"  → suno_api_wait_for_song('{clip.get('id', '')}')"
            )
        lines.append(
            "\n💡 Songs take 20–60 seconds to generate.\n"
            "   Use suno_api_wait_for_song(<id>) to get the audio URL when ready.\n"
            "   Use suno_api_download_song(<id>) to download directly."
        )
        return "\n".join(lines)

    async def _generate_via_browser(
        self,
        prompt: str,
        tags: str,
        title: str,
        make_instrumental: bool,
        mv: str,
        negative_tags: str = "",
        vocal_gender: Optional[str] = None,
        weirdness: int = 50,
        style_weight: int = 50,
    ) -> Dict[str, Any]:
        """
        Browser-assisted generation (route-intercept + Advanced-mode UI filling).

        Flow:
          1. Open suno.com/create in Advanced mode with session cookies
          2. Fill Lyrics + Style textareas (enables Create button; exact selectors used)
          3. Set Vocal Gender button if requested
          4. Set Weirdness + Style Influence sliders via keyboard
          5. Fill Song Title field
          6. Route-intercept /generate/v2-web/ to inject our REAL params
             (including weirdness_constraint, style_weight, vocal_gender at top level)
          7. Capture response clip IDs, close browser
        Browser window visible ~15s, closes automatically.
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise SunoError(
                "Playwright not installed. Run: pip install playwright && playwright install chromium",
                "PLAYWRIGHT_MISSING"
            )

        creds = get_credential_store()
        existing_jar = creds.get_cookie_jar()
        import uuid as _uuid

        generate_response: Dict[str, Any] = {}
        request_ready = asyncio.Event()

        # Advanced-mode selectors (confirmed by DOM inspection).
        # Primary: nth-child paths (stable); fallback: placeholder/ARIA text.
        SEL_LYRICS    = "#main-container div.card-popout-boundary div:nth-child(2) textarea"
        SEL_LYRICS_FB = "textarea[placeholder*='lyrics or a prompt']"
        SEL_STYLE     = "#main-container div.card-popout-boundary div:nth-child(3) textarea"
        SEL_STYLE_FB  = "textarea[placeholder*='drum']"
        SEL_WEIRDNESS = "[role='slider'][aria-label='Weirdness']"
        SEL_STYLE_INF = "[role='slider'][aria-label='Style Influence']"
        SEL_TITLE     = "#main-container div.card-popout-boundary div:nth-child(5) input"
        SEL_TITLE_FB  = "input[placeholder*='itle']"
        SEL_CREATE    = "button[aria-label='Create song']"

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=False,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/145.0.0.0 Safari/537.36"
                )
            )
            if existing_jar:
                await context.add_cookies([
                    {"name": k, "value": v, "domain": ".suno.com", "path": "/",
                     "secure": True, "httpOnly": k == "__client", "sameSite": "Lax"}
                    for k, v in existing_jar.items()
                ])

            page = await context.new_page()

            # Route intercept: keep hCaptcha token, inject our real params
            async def handle_generate(route, request):
                try:
                    original = json.loads(request.post_data or "{}")
                    try:
                        clerk_jwt = await page.evaluate(
                            "async () => { const c = window.Clerk; "
                            "return c?.session ? await c.session.getToken() : null; }"
                        )
                    except Exception:
                        clerk_jwt = None

                    new_body: Dict[str, Any] = {
                        "token": original.get("token", ""),
                        "generation_type": "TEXT",
                        "prompt": prompt,
                        "tags": tags,
                        "negative_tags": negative_tags or "",
                        "title": title,
                        "make_instrumental": make_instrumental,
                        "mv": mv,
                        "transaction_uuid": str(_uuid.uuid4()),
                        "continue_clip_id": None,
                        "continue_at": None,
                        "user_uploaded_images_b64": None,
                        "override_fields": [],
                        "cover_clip_id": None,
                        "cover_start_s": None,
                        "cover_end_s": None,
                        "persona_id": None,
                        "artist_clip_id": None,
                        "artist_start_s": None,
                        "artist_end_s": None,
                        "metadata": {
                            "web_client_pathname": "/create",
                            "is_max_mode": False,
                            "is_mumble": False,
                            "create_mode": "custom",
                            "create_session_token": str(_uuid.uuid4()),
                            "disable_volume_normalization": False,
                        },
                    }
                    if vocal_gender in ("male", "female"):
                        new_body["vocal_gender"] = vocal_gender
                    if weirdness != 50:
                        new_body["weirdness_constraint"] = weirdness
                    if style_weight != 50:
                        new_body["style_weight"] = style_weight

                    req_headers = dict(request.headers)
                    if clerk_jwt:
                        req_headers["authorization"] = f"Bearer {clerk_jwt}"
                    req_headers["content-type"] = "application/json"

                    self.logger.info(
                        "Intercepting generate -> model=%s  prompt=%d chars  weirdness=%s  style_weight=%s  vocal=%s",
                        mv, len(prompt), weirdness, style_weight, vocal_gender or "auto"
                    )
                    await route.continue_(post_data=json.dumps(new_body), headers=req_headers)
                except Exception as e:
                    self.logger.warning("Route intercept error: %s", e)
                    await route.continue_()

            await page.route("**/generate/v2-web/**", handle_generate)

            async def on_response(resp):
                if "generate/v2-web" in resp.url and resp.status == 200:
                    try:
                        data = await resp.json()
                        generate_response.update(data)
                        request_ready.set()
                    except Exception:
                        pass

            page.on("response", on_response)

            await page.goto("https://suno.com/create", wait_until="networkidle")
            await asyncio.sleep(2)

            # Ensure Advanced mode is active
            try:
                await page.locator("button:has-text('Advanced')").first.click(timeout=4000)
                await asyncio.sleep(0.8)
            except Exception:
                pass  # Already in Advanced mode

            # ── Helper: try primary selector, fall back to secondary ─────────────
            async def fill_field(primary: str, fallback: str, text: str, label: str) -> bool:
                for sel in (primary, fallback):
                    try:
                        el = page.locator(sel).first
                        await el.wait_for(state="visible", timeout=4000)
                        await el.click()
                        await page.keyboard.press("Control+a")
                        await el.press_sequentially(text, delay=6)
                        self.logger.info("Filled %s (%d chars)", label, len(text))
                        return True
                    except Exception:
                        continue
                self.logger.warning("Could not fill %s field", label)
                return False

            # ── Fill Lyrics textarea ──────────────────────────────────────────────
            await fill_field(SEL_LYRICS, SEL_LYRICS_FB, (prompt or "test")[:120], "lyrics")

            # ── Fill Style textarea ───────────────────────────────────────────────
            await fill_field(SEL_STYLE, SEL_STYLE_FB, (tags or "pop")[:60], "style")

            # ── Vocal Gender buttons ──────────────────────────────────────────────
            if vocal_gender in ("male", "female"):
                btn_text = "Male" if vocal_gender == "male" else "Female"
                try:
                    gender_btn = page.locator(f"button:has-text('{btn_text}')").first
                    await gender_btn.wait_for(state="visible", timeout=3000)
                    await gender_btn.click()
                    self.logger.info("Set vocal gender: %s", vocal_gender)
                except Exception as e:
                    self.logger.debug("Gender button not found: %s (set in body)", e)

            # ── Weirdness slider ─────────────────────────────────────────────────
            if weirdness != 50:
                try:
                    slider = page.locator(SEL_WEIRDNESS).first
                    await slider.wait_for(state="visible", timeout=3000)
                    await slider.focus()
                    # Arrow keys: each press moves +1/-1 on 0-100 scale
                    # From 50, calculate delta
                    delta = weirdness - 50
                    key = "ArrowRight" if delta > 0 else "ArrowLeft"
                    for _ in range(abs(delta)):
                        await page.keyboard.press(key)
                    self.logger.info("Set Weirdness slider to %d", weirdness)
                except Exception as e:
                    self.logger.debug("Weirdness slider: %s (set in body)", e)

            # ── Style Influence slider ────────────────────────────────────────────
            if style_weight != 50:
                try:
                    slider = page.locator(SEL_STYLE_INF).first
                    await slider.wait_for(state="visible", timeout=3000)
                    await slider.focus()
                    delta = style_weight - 50
                    key = "ArrowRight" if delta > 0 else "ArrowLeft"
                    for _ in range(abs(delta)):
                        await page.keyboard.press(key)
                    self.logger.info("Set Style Influence slider to %d", style_weight)
                except Exception as e:
                    self.logger.debug("Style Influence slider: %s (set in body)", e)

            # ── Song Title ────────────────────────────────────────────────────────
            if title:
                for sel in (SEL_TITLE, SEL_TITLE_FB):
                    try:
                        title_el = page.locator(sel).first
                        await title_el.wait_for(state="visible", timeout=3000)
                        await title_el.click()
                        await page.keyboard.press("Control+a")
                        await title_el.press_sequentially(title, delay=5)
                        self.logger.info("Filled title: %s", title)
                        break
                    except Exception:
                        continue

            # ── Create button ─────────────────────────────────────────────────────
            create_btn = page.locator(SEL_CREATE).first
            await create_btn.wait_for(state="visible", timeout=8000)
            for i in range(20):
                if not await create_btn.is_disabled():
                    self.logger.info("Create button enabled after %ds", i)
                    break
                await asyncio.sleep(1)
            else:
                self.logger.warning("Create button still disabled after 20s -- clicking anyway")

            try:
                await create_btn.click(timeout=5000)
            except Exception:
                await create_btn.click(force=True, timeout=5000)
            self.logger.info("Clicked Create button -- waiting for API response")

            try:
                await asyncio.wait_for(request_ready.wait(), timeout=30)
            except asyncio.TimeoutError:
                self.logger.warning("Generate response timed out after 30s")

            await browser.close()

        if not generate_response:
            raise SunoError(
                "Generation did not complete. Session may be expired. "
                "Run suno_browser_login() to re-authenticate.",
                "GENERATE_TIMEOUT"
            )

        return generate_response

    async def api_extend_song(
        self,
        song_id: str,
        prompt: str = "",
        tags: str = "",
        continue_at: float = 0.0,
        model: str = "v5",
    ) -> str:
        """
        Extend an existing song by continuing from where it ends (or a timestamp).

        Args:
            song_id: ID of the song to extend
            prompt: Additional lyrics/description for the extension
            continue_at: Timestamp in seconds to branch from (0 = end of song)
            model: Model version
        """
        client = get_api_client()
        data = await client.extend_song(
            clip_id=song_id,
            prompt=prompt,
            tags=tags,
            continue_at=continue_at if continue_at > 0 else None,
            model=self.SUNO_MODELS.get(model, model),
        )
        clips = data.get("clips", [])
        lines = [f"🔄 **Song Extended!**\n"]
        for clip in clips:
            lines.append(f"• ID: {clip.get('id', '?')} | Status: {clip.get('status', '?')}")
        return "\n".join(lines) if lines[1:] else f"Response: {json.dumps(data)[:400]}"

    async def api_remix_song(
        self,
        song_id: str,
        prompt: str,
        tags: str = "",
        title: str = "",
        model: str = "v5",
    ) -> str:
        """
        Remix an existing song with new style/lyrics.

        Args:
            song_id: ID of the source song to remix
            prompt: New style description or lyrics
            tags: New style tags (overrides original)
            title: New title for the remix
        """
        client = get_api_client()
        data = await client.remix_song(
            clip_id=song_id,
            prompt=prompt,
            tags=tags,
            title=title,
            model=self.SUNO_MODELS.get(model, model),
        )
        clips = data.get("clips", [])
        lines = [f"🎛️ **Remix Created!**\n"]
        for clip in clips:
            lines.append(f"• ID: {clip.get('id', '?')} | Status: {clip.get('status', '?')}")
        return "\n".join(lines) if lines[1:] else f"Response: {json.dumps(data)[:400]}"

    async def api_inpaint_song(
        self,
        song_id: str,
        start_seconds: float,
        end_seconds: float,
        prompt: str,
        tags: str = "",
    ) -> str:
        """
        Re-generate a specific section of an existing song (inpainting).

        Args:
            song_id: ID of the song to edit
            start_seconds: Start time of section to replace (in seconds)
            end_seconds: End time of section to replace (in seconds)
            prompt: Description or lyrics for the new section
        """
        client = get_api_client()
        data = await client.inpaint_song(
            clip_id=song_id,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            prompt=prompt,
            tags=tags,
        )
        clips = data.get("clips", [])
        lines = [f"✂️ **Song Inpainting Started!**\n"]
        for clip in clips:
            lines.append(f"• ID: {clip.get('id', '?')} | Status: {clip.get('status', '?')}")
        return "\n".join(lines) if lines[1:] else f"Response: {json.dumps(data)[:400]}"

    async def api_like_song(self, song_id: str) -> str:
        """Like/upvote a song."""
        client = get_api_client()
        data = await client.like_clip(song_id)
        return f"❤️ Liked song {song_id}\n{json.dumps(data)[:200]}"

    async def api_delete_song(self, song_id: str) -> str:
        """Move a song to trash (soft delete from your library)."""
        client = get_api_client()
        data = await client.delete_clip(song_id)
        return f"🗑️ Song {song_id} moved to trash.\n{json.dumps(data)[:200]}"

    async def api_make_public(self, song_id: str) -> str:
        """Make a song publicly visible on Suno."""
        client = get_api_client()
        data = await client.make_public(song_id)
        return f"🌐 Song {song_id} is now public.\n{json.dumps(data)[:200]}"

    async def api_create_playlist(self, name: str, description: str = "") -> str:
        """Create a new playlist."""
        client = get_api_client()
        data = await client.create_playlist(name, description)
        return (
            f"📋 Playlist created!\n"
            f"   Name: {data.get('name', name)}\n"
            f"   ID  : {data.get('id', '?')}"
        )

    async def api_add_to_playlist(self, playlist_id: str, song_id: str) -> str:
        """Add a song to a playlist."""
        client = get_api_client()
        data = await client.add_to_playlist(playlist_id, song_id)
        return f"✅ Added song {song_id} to playlist {playlist_id}\n{json.dumps(data)[:200]}"

    async def get_contests(self) -> str:
        """Get currently active Suno contests."""
        client = get_api_client()
        data = await client.get_contests()
        contests = data if isinstance(data, list) else data.get("contests", [])
        if not contests:
            return "🏆 No active contests right now."
        lines = ["🏆 **Active Contests**\n"]
        for c in contests:
            lines.append(
                f"• **{c.get('name', '?')}**\n"
                f"  ID: {c.get('id', '?')} | "
                f"Ends: {c.get('ends_at', '?')}"
            )
        return "\n".join(lines)

    async def get_liked_songs(self, page: int = 0) -> str:
        """
        Get songs you have liked/upvoted (requires auth).

        Args:
            page: Page number (0-based)
        """
        client = get_api_client()
        data = await client.get_liked_songs(page=page)
        if isinstance(data, list):
            clips, total = data, len(data)
        else:
            clips = data.get("clips", [])
            total = data.get("num_total_results", len(clips))
        lines = [f"❤️ **Liked Songs** (page {page + 1}) — {total} total\n"]
        for clip in clips[:20]:
            meta = clip.get("metadata", {}) or {}
            lines.append(
                f"• **{clip.get('title', '?')}** by @{clip.get('handle', '?')} | "
                f"{round(meta.get('duration', 0))}s | ID: {clip.get('id', '?')}"
            )
        lines.append(f"\nShowing {len(clips)} of {total}. Use page={page + 1} for more.")
        return "\n".join(lines)

    # ── Playlist Management ───────────────────────────────────────────────────

    async def api_remove_from_playlist(self, playlist_id: str, song_id: str) -> str:
        """
        Remove a song from one of your playlists.

        Args:
            playlist_id: The playlist UUID
            song_id: The song/clip UUID to remove
        """
        client = get_api_client()
        data = await client.remove_from_playlist(playlist_id, song_id)
        return f"✅ Removed song {song_id} from playlist {playlist_id}\n{json.dumps(data)[:200]}"

    async def api_update_playlist(
        self,
        playlist_id: str,
        name: str = "",
        description: str = "",
        is_public: Optional[bool] = None,
    ) -> str:
        """
        Rename or update a playlist.

        Args:
            playlist_id: The playlist UUID
            name: New name (leave blank to keep current)
            description: New description (leave blank to keep current)
            is_public: True to make public, False to make private, None to keep
        """
        client = get_api_client()
        data = await client.update_playlist(
            playlist_id, name=name, description=description, is_public=is_public
        )
        updated_name = data.get("name", name or "unchanged")
        return (
            f"📋 Playlist updated!\n"
            f"   ID  : {playlist_id}\n"
            f"   Name: {updated_name}"
        )

    # ── Download ──────────────────────────────────────────────────────────────

    async def wait_for_song(self, song_id: str, timeout: int = 120) -> str:
        """
        Poll a song until it finishes generating, then return its details.

        Use this after api_generate_track() to wait for the song to complete
        and get the final audio URL.

        Args:
            song_id: The clip UUID returned by api_generate_track()
            timeout: Maximum seconds to wait (default: 120)

        Returns:
            Song details with audio URL when ready, or timeout message.
        """
        client = get_api_client()
        deadline = asyncio.get_event_loop().time() + timeout
        last_status = "unknown"
        while asyncio.get_event_loop().time() < deadline:
            clip = await client.get_clip(song_id)
            status = clip.get("status", "unknown")
            last_status = status
            if status == "complete":
                return f"✅ **Song Ready!**\n\n{_fmt_clip(clip, verbose=True)}"
            if status in ("error", "failed"):
                return f"❌ Generation failed (status: {status})\nID: {song_id}"
            await asyncio.sleep(5)

        return (
            f"⏳ Timeout after {timeout}s — song still processing (status: {last_status})\n"
            f"   Try again: suno_api_wait_for_song('{song_id}')"
        )

    async def download_song(
        self,
        song_id: str,
        output_dir: str = "",
        include_cover: bool = True,
        wait_if_processing: bool = True,
    ) -> str:
        """
        Download a song's audio (MP3) and optionally its cover art to a local folder.

        Args:
            song_id: The song/clip UUID (from your library, trending, or search)
            output_dir: Folder to save to. Defaults to ~/Music/suno-downloads/
            include_cover: Also download the cover image (JPEG)
            wait_if_processing: If song is still generating, wait up to 120s

        Returns:
            Download summary with saved file paths.
        """
        client = get_api_client()
        clip = await client.get_clip(song_id)
        status = clip.get("status", "unknown")

        if status in ("queued", "streaming", "processing", "submitted") and wait_if_processing:
            wait_result = await self.wait_for_song(song_id, timeout=120)
            if "✅" in wait_result:
                clip = await client.get_clip(song_id)
            else:
                return wait_result

        audio_url = clip.get("audio_url") or ""
        image_url = clip.get("image_url") or ""
        if not audio_url:
            return (
                f"❌ No audio URL available for song {song_id}\n"
                f"   Status: {clip.get('status', '?')}\n"
                f"   The song may still be generating. Try wait_for_song('{song_id}') first."
            )

        # Build output path
        out_dir = pathlib.Path(output_dir).expanduser() if output_dir else (
            pathlib.Path.home() / "Music" / "suno-downloads"
        )
        out_dir.mkdir(parents=True, exist_ok=True)

        title = clip.get("title") or "untitled"
        safe_title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", title)[:60].strip()
        short_id = song_id[:8]
        base_name = f"{safe_title}_{short_id}"

        # Detect extension from URL
        ext = "mp3"
        if ".wav" in audio_url:
            ext = "wav"
        audio_path = out_dir / f"{base_name}.{ext}"

        saved_files = []

        # Download audio
        self.logger.info("Downloading audio: %s → %s", audio_url[:60], audio_path)
        audio_bytes = await client.download_audio_file(str(audio_url), str(audio_path))
        saved_files.append(f"Audio : {audio_path} ({audio_bytes // 1024}KB)")

        # Download cover art
        if include_cover and image_url:
            img_ext = "jpg"
            if ".png" in image_url:
                img_ext = "png"
            img_path = out_dir / f"{base_name}.{img_ext}"
            try:
                img_bytes = await client.download_audio_file(str(image_url), str(img_path))
                saved_files.append(f"Cover : {img_path} ({img_bytes // 1024}KB)")
            except Exception as e:
                saved_files.append(f"Cover : failed — {e}")

        meta = clip.get("metadata", {}) or {}
        return (
            f"⬇️ **Download Complete!**\n\n"
            f"Title    : {title}\n"
            f"Duration : {round(meta.get('duration', 0))}s\n"
            f"Tags     : {meta.get('tags', 'N/A')}\n\n"
            + "\n".join(saved_files)
        )

    async def download_playlist(
        self,
        playlist_id: str,
        output_dir: str = "",
        max_songs: int = 50,
    ) -> str:
        """
        Download all songs in a playlist to a local folder.

        Args:
            playlist_id: The playlist UUID
            output_dir: Folder to save to (defaults to ~/Music/suno-downloads/<playlist_name>/)
            max_songs: Maximum number of songs to download (default: 50)

        Returns:
            Summary of downloaded songs.
        """
        client = get_api_client()

        # Get all pages of the playlist
        all_clips: List[Dict] = []
        page = 0
        while len(all_clips) < max_songs:
            data = await client.get_playlist(playlist_id, page=page)
            items = data.get("playlist_clips", [])
            if not items:
                break
            all_clips.extend(items)
            if len(all_clips) >= data.get("num_total_results", len(all_clips)):
                break
            page += 1

        playlist_name = data.get("name", playlist_id[:8])  # type: ignore[possibly-undefined]
        safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", playlist_name)[:40]

        out_dir = pathlib.Path(output_dir).expanduser() if output_dir else (
            pathlib.Path.home() / "Music" / "suno-downloads" / safe_name
        )
        out_dir.mkdir(parents=True, exist_ok=True)

        results: List[str] = [f"📥 **Downloading playlist: {playlist_name}** ({len(all_clips[:max_songs])} songs)\n"]
        ok = failed = 0
        for item in all_clips[:max_songs]:
            clip = item.get("clip", item)
            cid = clip.get("id", "")
            title = clip.get("title", "untitled")
            audio_url = clip.get("audio_url") or ""
            if not audio_url or not cid:
                results.append(f"  ⚠ Skipped: {title} (no audio URL)")
                failed += 1
                continue
            try:
                result = await self.download_song(
                    cid, output_dir=str(out_dir), wait_if_processing=False
                )
                ok += 1
                results.append(f"  ✅ {title}")
            except Exception as e:
                failed += 1
                results.append(f"  ❌ {title}: {e}")

        results.append(f"\nDone: {ok} downloaded, {failed} failed → {out_dir}")
        return "\n".join(results)

    async def download_my_songs(
        self,
        output_dir: str = "",
        page: int = 0,
        max_songs: int = 20,
        only_complete: bool = True,
    ) -> str:
        """
        Batch download songs from your personal library.

        Args:
            output_dir: Folder to save to (defaults to ~/Music/suno-downloads/my-songs/)
            page: Library page to start from (0-based)
            max_songs: Maximum songs to download in this batch (default: 20)
            only_complete: Skip songs that haven't finished generating (default: True)

        Returns:
            Summary of downloaded songs.
        """
        client = get_api_client()
        data = await client.get_feed(page=page)
        clips = data.get("clips", [])
        total = data.get("num_total_results", len(clips))

        out_dir = pathlib.Path(output_dir).expanduser() if output_dir else (
            pathlib.Path.home() / "Music" / "suno-downloads" / "my-songs"
        )
        out_dir.mkdir(parents=True, exist_ok=True)

        results: List[str] = [
            f"📥 **Downloading my songs** (page {page + 1}, {len(clips)} songs available)\n"
        ]
        ok = skipped = failed = 0
        for clip in clips[:max_songs]:
            status = clip.get("status", "unknown")
            title = clip.get("title", "untitled")
            cid = clip.get("id", "")

            if only_complete and status != "complete":
                results.append(f"  ⏭ Skipped: {title} (status: {status})")
                skipped += 1
                continue

            try:
                await self.download_song(cid, output_dir=str(out_dir), wait_if_processing=False)
                ok += 1
                results.append(f"  ✅ {title}")
            except Exception as e:
                failed += 1
                results.append(f"  ❌ {title}: {e}")

        results.append(
            f"\nDone: {ok} downloaded, {skipped} skipped, {failed} failed\n"
            f"Total in library: {total} | Use page={page + 1} for next batch\n"
            f"Saved to: {out_dir}"
        )
        return "\n".join(results)
