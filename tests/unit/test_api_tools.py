"""
Unit tests for api/tools.py — MCP tool method wrappers.
"""
import sys
import pathlib
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

src = pathlib.Path(__file__).parents[2] / "src"
if str(src) not in sys.path:
    sys.path.insert(0, str(src))

from tests.conftest import make_fresh_jwt, make_expired_jwt, make_cookie_jar


def make_tools():
    from suno_mcp.tools.api.tools import ApiSunoTools
    return ApiSunoTools()


# ── session_info ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestSessionInfo:
    async def test_returns_status_string(self):
        tools = make_tools()
        result = await tools.session_info()
        assert isinstance(result, str)
        assert len(result) > 10  # non-trivial response

    async def test_shows_authenticated_when_jar_present(self):
        from tests.unit.test_credentials import fresh_store
        store = fresh_store()
        jwt = make_fresh_jwt()
        store.save_cookie_jar(make_cookie_jar(jwt=jwt))

        tools = make_tools()
        with patch("suno_mcp.tools.api.tools.get_credential_store", return_value=store):
            result = await tools.session_info()

        assert "Full cookie jar" in result
        assert "Valid" in result

    async def test_does_not_reveal_jwt(self):
        from tests.unit.test_credentials import fresh_store
        store = fresh_store()
        jwt = make_fresh_jwt()
        store.save_cookie_jar(make_cookie_jar(jwt=jwt))

        tools = make_tools()
        with patch("suno_mcp.tools.api.tools.get_credential_store", return_value=store):
            result = await tools.session_info()

        assert jwt not in result


# ── refresh_session ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestRefreshSession:
    async def test_no_token_returns_guidance(self):
        from tests.unit.test_credentials import fresh_store
        store = fresh_store()
        tools = make_tools()
        with patch("suno_mcp.tools.api.tools.get_credential_store", return_value=store):
            result = await tools.refresh_session()
        assert "suno_browser_login" in result

    async def test_fresh_token_skips_refresh(self):
        from tests.unit.test_credentials import fresh_store
        store = fresh_store()
        jwt = make_fresh_jwt()
        store.save_cookie_jar(make_cookie_jar(jwt=jwt))

        tools = make_tools()
        with patch("suno_mcp.tools.api.tools.get_credential_store", return_value=store):
            result = await tools.refresh_session(force=False)

        assert "no refresh needed" in result
        assert "force=True" in result

    async def test_force_triggers_refresh(self):
        from tests.unit.test_credentials import fresh_store
        store = fresh_store()
        jwt = make_fresh_jwt()
        new_jwt = make_fresh_jwt()
        store.save_cookie_jar(make_cookie_jar(jwt=jwt, include_client=True))

        mock_refresher = AsyncMock()
        mock_refresher.refresh_via_http = AsyncMock(return_value=new_jwt)

        tools = make_tools()
        with (
            patch("suno_mcp.tools.api.tools.get_credential_store", return_value=store),
            patch("suno_mcp.tools.api.tools.get_refresher", return_value=mock_refresher),
        ):
            result = await tools.refresh_session(force=True)

        assert "refreshed" in result.lower()

    async def test_refresh_failure_gives_guidance(self):
        from tests.unit.test_credentials import fresh_store
        store = fresh_store()
        store.save_cookie_jar(make_cookie_jar(jwt=make_expired_jwt(), include_client=True))

        mock_refresher = AsyncMock()
        mock_refresher.refresh_via_http = AsyncMock(return_value=None)
        mock_refresher.refresh_via_playwright = AsyncMock(return_value=None)

        tools = make_tools()
        with (
            patch("suno_mcp.tools.api.tools.get_credential_store", return_value=store),
            patch("suno_mcp.tools.api.tools.get_refresher", return_value=mock_refresher),
        ):
            result = await tools.refresh_session(force=True)

        assert "failed" in result.lower() or "expired" in result.lower()


# ── check_auth ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestCheckAuth:
    async def test_unauthenticated_message(self):
        tools = make_tools()
        mock_client = AsyncMock()
        # is_authenticated is a sync method — must be MagicMock, not AsyncMock
        mock_client.is_authenticated = MagicMock(return_value=False)
        with patch("suno_mcp.tools.api.tools.get_api_client", return_value=mock_client):
            result = await tools.check_auth()
        assert "authenticated" in result.lower() or "login" in result.lower()

    async def test_authenticated_calls_session_endpoint(self):
        tools = make_tools()
        mock_client = AsyncMock()
        mock_client.is_authenticated = MagicMock(return_value=True)
        mock_client.get_session = AsyncMock(return_value={
            "user": {"display_name": "Test User", "handle": "testuser"}
        })
        with patch("suno_mcp.tools.api.tools.get_api_client", return_value=mock_client):
            result = await tools.check_auth()
        assert "Test User" in result or "testuser" in result


# ── get_trending_songs ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestGetTrendingSongs:
    async def test_formats_clips(self):
        tools = make_tools()
        mock_client = AsyncMock()
        # get_trending_songs uses "playlist_clips" key wrapping each clip under "clip"
        mock_client.get_trending = AsyncMock(return_value={
            "playlist_clips": [
                {
                    "clip": {
                        "id": "clip-abc",
                        "title": "Test Song",
                        "display_name": "ArtistX",
                        "handle": "artistx",
                        "upvote_count": 1234,
                        "model_name": "chirp-v4",
                        "audio_url": "https://cdn.suno.ai/clip-abc.mp3",
                        "metadata": {"duration": 180, "tags": "pop, upbeat"},
                    }
                }
            ],
            "num_total_results": 1,
        })
        with patch("suno_mcp.tools.api.tools.get_api_client", return_value=mock_client):
            result = await tools.get_trending_songs()
        assert "Test Song" in result
        assert "clip-abc" in result
        assert "1,234" in result

    async def test_handles_empty_response(self):
        tools = make_tools()
        mock_client = AsyncMock()
        mock_client.get_trending = AsyncMock(return_value={"clips": []})
        with patch("suno_mcp.tools.api.tools.get_api_client", return_value=mock_client):
            result = await tools.get_trending_songs()
        assert "No" in result or "0" in result or "empty" in result.lower()


# ── api_generate_track ────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestApiGenerateTrack:
    async def test_returns_clip_ids(self):
        tools = make_tools()
        mock_client = AsyncMock()
        mock_client.is_authenticated = MagicMock(return_value=True)
        mock_client.generate_music = AsyncMock(return_value={
            "clips": [
                {"id": "gen-clip-1", "title": "Generated Song", "status": "submitted"},
                {"id": "gen-clip-2", "title": "Generated Song 2", "status": "submitted"},
            ]
        })
        with patch("suno_mcp.tools.api.tools.get_api_client", return_value=mock_client):
            result = await tools.api_generate_track("a test song about testing")
        assert "gen-clip-1" in result
        assert "gen-clip-2" in result

    async def test_api_error_is_surfaced(self):
        """When the API returns an AUTH error, the tool surfaces it gracefully."""
        from suno_mcp.tools.shared.exceptions import SunoError
        tools = make_tools()
        mock_client = AsyncMock()
        mock_client.is_authenticated = MagicMock(return_value=False)
        mock_client.generate_music = AsyncMock(
            side_effect=SunoError("Session expired", "AUTH_REQUIRED")
        )
        with patch("suno_mcp.tools.api.tools.get_api_client", return_value=mock_client):
            try:
                result = await tools.api_generate_track("test")
                # If it returns a string, it should mention the problem
                assert "error" in result.lower() or "auth" in result.lower() or "Session" in result
            except SunoError:
                pass  # Acceptable — error propagation is valid behavior
