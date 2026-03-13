"""
Suno API Client - Direct HTTP interface to studio-api.prod.suno.com

Discovered endpoints via network interception on suno.com.
Authentication uses Clerk JWT session tokens stored securely via
the OS credential vault (see credentials.py).

Credential sources (in priority order):
  1. OS keychain  — saved via suno_api_save_credentials() MCP tool
  2. SUNO_COOKIE env var  — for CI / Docker / headless environments
  3. SUNO_AUTH_TOKEN env var — raw Bearer token alternative
  4. In-process token — set via suno_login() browser flow
"""

import asyncio
import base64
import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

import httpx

from .credentials import get_credential_store
from .exceptions import SunoError
from .session_manager import (
    build_cookie_header,
    get_refresher,
    is_token_expired,
)

logger = logging.getLogger(__name__)

API_BASE = "https://studio-api.prod.suno.com/api"
AUTH_BASE = "https://auth.suno.com/v1"
CLERK_API_VERSION = "2025-11-10"


def _make_browser_token() -> str:
    """Generate Suno browser-token header value (base64 JSON with timestamp)."""
    payload = {"timestamp": int(time.time() * 1000)}
    return base64.b64encode(json.dumps(payload).encode()).decode()


class SunoApiClient:
    """
    Direct HTTP client for the Suno API.

    Credentials are resolved through the secure CredentialStore (OS keychain →
    env var → in-process token).  Raw secret values are never logged.
    """

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)
        self._creds = get_credential_store()
        self._device_id = self._creds.get_device_id()
        self._client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(60.0),
                follow_redirects=True,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/145.0.0.0 Safari/537.36"
                    ),
                    "Origin": "https://suno.com",
                    "Referer": "https://suno.com/",
                    "Accept": "application/json, */*",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
        return self._client

    def _get_auth_headers(self) -> Dict[str, str]:
        """Build authentication headers via the secure credential store."""
        headers: Dict[str, str] = {
            "browser-token": json.dumps({"token": _make_browser_token()}),
            "device-id": self._device_id,
        }

        # Prefer: full cookie jar → legacy cookie string → bare token
        jar = self._creds.get_cookie_jar()
        if jar:
            headers["Cookie"] = build_cookie_header(jar)
            jwt = jar.get("__session") or next(
                (v for k, v in jar.items() if k.startswith("__session_")), None
            )
            if jwt:
                headers["Authorization"] = f"Bearer {jwt}"
        else:
            cookie = self._creds.get_cookie()
            if cookie:
                headers["Cookie"] = cookie
                for part in cookie.split(";"):
                    part = part.strip()
                    if part.startswith("__session="):
                        headers["Authorization"] = f"Bearer {part[len('__session='):]}"
                        break

        if "Authorization" not in headers:
            token = self._creds.get_token()
            if token:
                headers["Authorization"] = f"Bearer {token}"

        return headers

    async def _ensure_fresh_token(self) -> None:
        """
        Check if the current __session JWT is expired (or expiring soon).
        If so, attempt to refresh it via the Clerk API before making an API call.

        This is called automatically before every authenticated request.
        """
        current_jwt = self._creds.get_current_jwt()
        if not current_jwt:
            return  # No token yet — user hasn't logged in

        if not is_token_expired(current_jwt):
            return  # Token still fresh — no refresh needed

        logger.info("__session JWT is expiring — attempting silent refresh")

        jar = self._creds.get_cookie_jar()
        session_id = self._creds.get_session_id()

        if not session_id:
            logger.warning("No session ID stored — cannot refresh token")
            return

        refresher = get_refresher()

        # Strategy 1: HTTP refresh via Clerk API (fast, no browser)
        if jar and "__client" in jar:
            new_jwt = await refresher.refresh_via_http(session_id, jar)
            if new_jwt:
                self._creds.update_session_token(new_jwt)
                logger.info("Token refreshed via Clerk HTTP API")
                return

        # Strategy 2: Headless browser refresh (fallback — slower)
        logger.info("HTTP refresh failed or no __client cookie — trying browser fallback")
        if jar:
            result = await refresher.refresh_via_playwright(jar)
            if result:
                new_jwt, new_jar = result  # type: ignore[misc]
                self._creds.update_session_token(new_jwt, updated_jar=new_jar)
                logger.info("Token refreshed via browser fallback")
                return

        logger.error(
            "Token refresh failed. The session may have expired. "
            "Run suno_browser_login() to re-authenticate."
        )

    def set_session_token(self, token: str) -> None:
        """Persist a token obtained via browser login into the secure store."""
        self._creds.save_token(token)
        logger.debug("Session token updated via browser login")

    def is_authenticated(self) -> bool:
        """True if any credential is available (keychain, env, or in-process)."""
        return self._creds.is_configured()

    # ─── Private helpers ──────────────────────────────────────────────────────

    async def _get(self, path: str, params: Optional[Dict] = None) -> Any:
        await self._ensure_fresh_token()
        client = self._get_client()
        url = f"{API_BASE}{path}"
        resp = await client.get(url, params=params, headers=self._get_auth_headers())
        self._check_response(resp)
        return resp.json()

    async def _post(self, path: str, body: Optional[Dict] = None) -> Any:
        await self._ensure_fresh_token()
        client = self._get_client()
        url = f"{API_BASE}{path}"
        resp = await client.post(url, json=body or {}, headers={
            **self._get_auth_headers(),
            "Content-Type": "application/json",
        })
        self._check_response(resp)
        return resp.json()

    def _check_response(self, resp: httpx.Response) -> None:
        if resp.status_code == 401:
            raise SunoError(
                "Session expired or not authenticated. "
                "Run suno_browser_login() to log in — the MCP will then "
                "refresh your session automatically.",
                "AUTH_REQUIRED"
            )
        if resp.status_code == 403:
            raise SunoError("Access forbidden. Check your subscription plan.", "FORBIDDEN")
        if resp.status_code == 429:
            raise SunoError("Rate limited. Please wait before retrying.", "RATE_LIMITED")
        if resp.status_code >= 400:
            detail = ""
            try:
                detail = resp.json().get("detail", resp.text[:200])
            except Exception:
                detail = resp.text[:200]
            raise SunoError(f"API error {resp.status_code}: {detail}", "API_ERROR")

    # ─── Public endpoints (no auth needed) ────────────────────────────────────

    async def get_trending(self, page: int = 0, period: Optional[str] = None) -> Dict:
        """
        Fetch trending songs.
        period: None (all-time) | 'week' | 'day'
        """
        params: Dict[str, Any] = {"page": page}
        if period:
            params["period"] = period
        return await self._get("/trending/", params=params)

    async def get_playlist(self, playlist_id: str, page: int = 0) -> Dict:
        """Get a public playlist by ID."""
        return await self._get(f"/playlist/{playlist_id}", params={"page": page})

    async def get_clip(self, clip_id: str) -> Dict:
        """Get a single song/clip by its ID (public if song is public)."""
        return await self._get(f"/clip/{clip_id}")

    async def search_songs(self, term: str, search_type: str = "audio", page: int = 0) -> Dict:
        """
        Search for songs/users/playlists.
        search_type: 'audio' | 'playlist' | 'user'
        """
        body = {
            "search_request": {
                "search_queries": [{"search_type": search_type, "term": term, "page": page}]
            }
        }
        return await self._post("/search/", body)

    async def get_billing_plans(self) -> Dict:
        """Get available subscription plans (public)."""
        return await self._get("/billing/usage-plans")

    async def get_contests(self) -> Dict:
        """Get active contests (public)."""
        return await self._get("/contests/")

    # ─── Authenticated endpoints ──────────────────────────────────────────────

    async def get_session(self) -> Dict:
        """Get current user session info."""
        return await self._get("/session/")

    async def get_user_session_id(self) -> Dict:
        """Get user session ID."""
        return await self._get("/user/get_user_session_id/")

    async def get_credits(self) -> Dict:
        """Get user's remaining credits."""
        return await self._get("/billing/credits/")

    async def get_billing_info(self) -> Dict:
        """Get full billing/subscription info."""
        return await self._get("/billing/info/")

    async def get_feed(self, page: int = 0) -> Dict:
        """Get the user's personal song feed/library."""
        return await self._get("/feed/", params={"page": page})

    async def get_saved_prompts(self, prompt_type: str = "lyrics") -> List[Dict]:
        """
        Get user's saved prompts.
        prompt_type: 'lyrics' | 'tags'
        """
        return await self._get(
            "/prompts/",
            params={"page": 0, "per_page": 100, "filter_prompt_type": prompt_type},
        )

    async def generate_music(
        self,
        prompt: str,
        tags: str = "",
        title: str = "",
        make_instrumental: bool = False,
        model: str = "chirp-crow",
        continue_clip_id: Optional[str] = None,
        continue_at: Optional[float] = None,
        mv: Optional[str] = None,
        # Advanced v5 parameters
        negative_tags: str = "",
        vocal_gender: Optional[str] = None,
        weirdness: Optional[int] = None,
        style_weight: Optional[int] = None,
    ) -> Dict:
        """
        Generate a new song via the Suno API.

        Args:
            prompt: Lyric content OR song description
            tags: Style tags (e.g., "Hungarian rap, 90s, male vocals")
            title: Song title
            make_instrumental: Generate without vocals
            model: Model version — see SUNO_MODELS dict for choices
            continue_clip_id: Clip ID to extend/continue from
            continue_at: Timestamp in seconds to continue from
            mv: Model version override (takes precedence over model)
            negative_tags: Styles/tags to actively exclude
            vocal_gender: "male" | "female" | None (auto)
            weirdness: 0–100, how experimental/unexpected the output is (default 50)
            style_weight: 0–100, how strongly the style tags are applied (default 50)
        """
        # The web endpoint (/generate/v2-web/) requires a Cloudflare Turnstile token.
        # We use the API endpoint (/generate/v2/) which accepts the same body without it.
        body: Dict[str, Any] = {
            "prompt": prompt,
            "tags": tags,
            "negative_tags": negative_tags or "",
            "title": title,
            "make_instrumental": make_instrumental,
            "mv": mv or model,
            "generation_type": "TEXT",
            "continue_clip_id": continue_clip_id,
            "continue_at": continue_at,
            "transaction_uuid": str(uuid.uuid4()),
            # Extra web fields that the API also accepts
            "user_uploaded_images_b64": None,
            "override_fields": [],
            "cover_clip_id": None,
            "persona_id": None,
            "artist_clip_id": None,
            "metadata": {
                "create_mode": "custom",
                "is_max_mode": False,
                "create_session_token": str(uuid.uuid4()),
            },
        }
        if vocal_gender in ("male", "female"):
            body["vocal_gender"] = vocal_gender
        if weirdness is not None:
            body["metadata"]["weirdness"] = max(0, min(100, weirdness))
        if style_weight is not None:
            body["metadata"]["style_weight"] = max(0, min(100, style_weight))

        return await self._post("/generate/v2/", body)

    async def extend_song(
        self,
        clip_id: str,
        prompt: str = "",
        tags: str = "",
        title: str = "",
        continue_at: Optional[float] = None,
        model: str = "chirp-v4",
    ) -> Dict:
        """
        Extend an existing song beyond its current length.

        Args:
            clip_id: ID of the song to extend
            prompt: New prompt for the extension (optional)
            continue_at: Timestamp in seconds to branch from (optional)
        """
        body: Dict[str, Any] = {
            "continue_clip_id": clip_id,
            "prompt": prompt,
            "tags": tags,
            "title": title,
            "mv": model,
        }
        if continue_at is not None:
            body["continue_at"] = continue_at
        return await self._post("/generate/v2/", body)

    async def remix_song(
        self,
        clip_id: str,
        prompt: str,
        tags: str = "",
        title: str = "",
        model: str = "chirp-v4",
    ) -> Dict:
        """
        Remix an existing song with a new prompt.

        Args:
            clip_id: ID of the source song
            prompt: New style/lyric description
            tags: New style tags
        """
        body: Dict[str, Any] = {
            "prompt": prompt,
            "tags": tags,
            "title": title,
            "mv": model,
            "source_clip_id": clip_id,
        }
        return await self._post("/generate/v2/", body)

    async def inpaint_song(
        self,
        clip_id: str,
        start_seconds: float,
        end_seconds: float,
        prompt: str,
        tags: str = "",
    ) -> Dict:
        """
        Re-generate a specific section of an existing song.

        Args:
            clip_id: ID of the song to edit
            start_seconds: Start time of the section to replace
            end_seconds: End time of the section to replace
            prompt: Description for the new section
        """
        body: Dict[str, Any] = {
            "clip_id": clip_id,
            "start_seconds": start_seconds,
            "end_seconds": end_seconds,
            "prompt": prompt,
            "tags": tags,
        }
        return await self._post("/inpaint/", body)

    async def like_clip(self, clip_id: str) -> Dict:
        """Like/upvote a song."""
        return await self._post(f"/clips/{clip_id}/upvote/")

    async def get_my_clips(self, page: int = 0) -> Dict:
        """Get user's own generated clips."""
        return await self._get("/feed/", params={"page": page})

    async def delete_clip(self, clip_id: str) -> Dict:
        """Soft-delete (trash) a clip from user library."""
        return await self._post(f"/clips/{clip_id}/trash/")

    async def make_public(self, clip_id: str) -> Dict:
        """Make a clip publicly visible."""
        return await self._post(f"/clips/{clip_id}/set_public/")

    async def create_playlist(self, name: str, description: str = "") -> Dict:
        """Create a new playlist."""
        return await self._post("/playlist/create/", {
            "name": name,
            "description": description,
            "is_public": True,
        })

    async def add_to_playlist(self, playlist_id: str, clip_id: str) -> Dict:
        """Add a song to a playlist."""
        return await self._post(f"/playlist/{playlist_id}/add_clip/", {"clip_id": clip_id})

    async def remove_from_playlist(self, playlist_id: str, clip_id: str) -> Dict:
        """Remove a song from a playlist."""
        return await self._post(f"/playlist/{playlist_id}/remove_clip/", {"clip_id": clip_id})

    async def update_playlist(
        self, playlist_id: str, name: str = "", description: str = "", is_public: Optional[bool] = None
    ) -> Dict:
        """Update playlist metadata (name, description, visibility)."""
        body: Dict[str, Any] = {}
        if name:
            body["name"] = name
        if description:
            body["description"] = description
        if is_public is not None:
            body["is_public"] = is_public
        return await self._post(f"/playlist/{playlist_id}/update/", body)

    async def get_user_playlists(self, page: int = 0) -> Dict:
        """Get user's playlists."""
        return await self._get("/playlist/me/", params={"page": page})

    async def get_liked_songs(self, page: int = 0) -> Dict:
        """Get user's liked/upvoted songs."""
        return await self._get("/feed/", params={"page": page, "filter": "liked"})

    async def download_audio_file(
        self,
        url: str,
        dest_path: str,
        progress_callback: Optional[Any] = None,
    ) -> int:
        """
        Stream-download a media file (audio or image) from a CDN URL.

        Args:
            url: Direct CDN URL for the audio/image file
            dest_path: Absolute path to save the file
            progress_callback: Optional callable(downloaded_bytes, total_bytes)

        Returns:
            Total bytes written.
        """
        import os as _os
        _os.makedirs(_os.path.dirname(_os.path.abspath(dest_path)), exist_ok=True)

        # CDN files don't need auth headers — a plain httpx client is fine
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(300.0),
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; suno-mcp/1.0)"},
        ) as dl_client:
            async with dl_client.stream("GET", url) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("content-length", 0))
                downloaded = 0
                with open(dest_path, "wb") as fh:
                    async for chunk in resp.aiter_bytes(chunk_size=65536):
                        fh.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback:
                            progress_callback(downloaded, total)
        return downloaded

    # ─── Persona ──────────────────────────────────────────────────────────────

    async def get_persona(self, persona_id: str, page: int = 1) -> Dict:
        """
        Fetch a Persona and its clips (paginated).

        Endpoint: GET /api/persona/get-persona-paginated/{persona_id}/?page={page}

        Returns:
            {persona: {id, name, description, root_clip_id, clip, ...},
             total_results, current_page, is_following}
        """
        return await self._get(
            f"/persona/get-persona-paginated/{persona_id}/",
            params={"page": page},
        )

    async def get_my_personas(self, page: int = 0) -> Dict:
        """Fetch personas owned by the current user."""
        return await self._get("/persona/", params={"page": page, "filter": "owned"})

    async def get_featured_personas(self, page: int = 0) -> Dict:
        """Fetch Suno's curated/featured personas."""
        return await self._get("/persona/", params={"page": page, "filter": "featured"})

    # ─── Lyrics generation ────────────────────────────────────────────────────

    async def generate_lyrics(self, prompt: str, poll_timeout: float = 30.0) -> Dict:
        """
        Generate AI lyrics from a topic/theme, with blocking poll until complete.

        Endpoint: POST /api/generate/lyrics/
        Poll:     GET  /api/generate/lyrics/{id}  until status == 'complete'

        Returns:
            {id, status, title, text}
        """
        import asyncio as _asyncio

        resp = await self._post("/generate/lyrics/", {"prompt": prompt})
        gen_id = resp.get("id")
        if not gen_id:
            return resp

        deadline = _asyncio.get_event_loop().time() + poll_timeout
        while _asyncio.get_event_loop().time() < deadline:
            poll = await self._get(f"/generate/lyrics/{gen_id}")
            if poll.get("status") == "complete":
                return poll
            await _asyncio.sleep(2)

        return {"id": gen_id, "status": "timeout", "text": ""}

    # ─── Stems ────────────────────────────────────────────────────────────────

    async def generate_stems(self, song_id: str) -> Dict:
        """
        Separate a song into its individual stems (vocals, drums, bass, etc.).

        Endpoint: POST /api/edit/stems/{song_id}
        Premier plan required.
        """
        return await self._post(f"/edit/stems/{song_id}", {})

    # ─── Concat ───────────────────────────────────────────────────────────────

    async def concat_song(self, clip_id: str) -> Dict:
        """
        Concatenate extended clips back into a single full-length song.

        Endpoint: POST /api/generate/concat/v2/
        """
        return await self._post("/generate/concat/v2/", {"clip_id": clip_id})

    # ─── Lyric alignment ──────────────────────────────────────────────────────

    async def get_lyric_alignment(self, song_id: str) -> Dict:
        """
        Get word-level lyric timestamps (karaoke-style alignment).

        Endpoint: GET /api/gen/{song_id}/aligned_lyrics/v2/

        Returns list of {word, start_s, end_s, success, p_align}
        """
        return await self._get(f"/gen/{song_id}/aligned_lyrics/v2/")

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()


# Shared singleton
_api_client: Optional[SunoApiClient] = None


def get_api_client() -> SunoApiClient:
    """Get or create the shared API client instance."""
    global _api_client
    if _api_client is None:
        _api_client = SunoApiClient()
    return _api_client
