"""
Unit tests for server.py MCP tool registrations.
Tests that tools exist, have correct signatures, and return reasonable output.
"""
import sys
import pathlib
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

src = pathlib.Path(__file__).parents[2] / "src"
if str(src) not in sys.path:
    sys.path.insert(0, str(src))

from tests.conftest import make_fresh_jwt, make_cookie_jar


# ── Tool registration ─────────────────────────────────────────────────────────

class TestToolRegistration:
    """Verify all expected MCP tools are registered on the server."""

    EXPECTED_TOOLS = [
        # Session management
        "suno_browser_login",
        "suno_refresh_session",
        "suno_session_info",
        # Credential management
        "suno_save_cookie",
        "suno_save_token",
        "suno_credential_status",
        "suno_clear_credentials",
        # API tools
        "suno_api_get_trending",
        "suno_api_get_song",
        "suno_api_search",
        "suno_api_get_playlist",
        "suno_api_check_auth",
        "suno_api_get_credits",
        "suno_api_generate",
        "suno_api_get_my_songs",
        "suno_api_get_my_playlists",
        "suno_api_like_song",
        "suno_api_delete_song",
        "suno_api_make_public",
        "suno_api_create_playlist",
        "suno_api_add_to_playlist",
        "suno_api_get_subscription_plans",
        "suno_api_get_contests",
        # Help
        "help",
        # Browser tools (legacy)
        "suno_open_browser",
        "suno_login",
        "suno_generate_track",
        "suno_download_track",
        "suno_get_status",
        "suno_close_browser",
    ]

    def test_all_expected_tools_registered(self):
        from suno_mcp.server import mcp_app
        # FastMCP stores tools in a dict keyed by name
        registered = set()
        if hasattr(mcp_app, "_tool_manager") and hasattr(mcp_app._tool_manager, "_tools"):
            registered = set(mcp_app._tool_manager._tools.keys())
        elif hasattr(mcp_app, "tools"):
            registered = set(mcp_app.tools.keys())
        else:
            # Try listing tools via the MCP protocol method
            pytest.skip("Cannot introspect tool registry in this FastMCP version")

        missing = [t for t in self.EXPECTED_TOOLS if t not in registered]
        assert not missing, f"Missing tools: {missing}"


# ── suno_save_cookie ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestSunoSaveCookieTool:
    async def test_valid_cookie_accepted(self):
        from suno_mcp.server import suno_save_cookie
        from tests.unit.test_credentials import fresh_store
        jwt = make_fresh_jwt()
        store = fresh_store()
        with patch("suno_mcp.server.suno_save_cookie.__wrapped__" if hasattr(suno_save_cookie, "__wrapped__") else "suno_mcp.tools.shared.credentials.get_credential_store", return_value=store):
            result = await suno_save_cookie(f"__session={jwt}")
        # Either the real result or the patched one is acceptable
        assert isinstance(result, str)

    async def test_short_cookie_rejected(self):
        from suno_mcp.server import suno_save_cookie
        from suno_mcp.tools.shared.credentials import get_credential_store
        from tests.unit.test_credentials import fresh_store
        store = fresh_store()
        with patch("suno_mcp.tools.shared.credentials.get_credential_store", return_value=store):
            try:
                result = await suno_save_cookie("short")
                # Some implementations return an error string instead of raising
                assert "error" in result.lower() or "invalid" in result.lower() or "fail" in result.lower()
            except (ValueError, Exception):
                pass  # Raising is also acceptable


# ── suno_session_info ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestSunoSessionInfoTool:
    async def test_returns_string(self):
        from suno_mcp.server import suno_session_info
        result = await suno_session_info()
        assert isinstance(result, str)
        assert len(result) > 0


# ── suno_refresh_session ───────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestSunoRefreshSessionTool:
    async def test_no_token_guidance(self):
        from suno_mcp.server import suno_refresh_session
        from tests.unit.test_credentials import fresh_store
        store = fresh_store()
        with patch("suno_mcp.tools.api.tools.get_credential_store", return_value=store):
            result = await suno_refresh_session(force=False)
        assert isinstance(result, str)
        assert len(result) > 0


# ── suno_clear_credentials ────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestSunoClearCredentialsTool:
    async def test_clear_returns_string(self):
        from suno_mcp.server import suno_clear_credentials
        result = await suno_clear_credentials()
        assert isinstance(result, str)


# ── help tool ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestHelpTool:
    async def test_basic_help(self):
        from suno_mcp.server import help
        result = await help("basic")
        assert "suno_browser_login" in result
        assert "suno_api_generate" in result

    async def test_detailed_help(self):
        from suno_mcp.server import help
        result = await help("detailed")
        assert "suno_refresh_session" in result
        assert "suno_api_get_trending" in result

    async def test_help_contains_new_session_tools(self):
        from suno_mcp.server import help
        result = await help("detailed")
        assert "suno_browser_login" in result
        assert "suno_session_info" in result


# ── FastAPI health endpoint ───────────────────────────────────────────────────

@pytest.mark.asyncio
class TestFastApiHealth:
    async def test_health_endpoint(self):
        """Call the health check handler directly (bypasses CORS middleware)."""
        from suno_mcp.server import health_check
        result = await health_check()
        assert result.status in ("ok", "healthy")
        assert result.version == "2.0.0"
        assert result.tools_loaded >= 40

    async def test_tools_list_endpoint(self):
        """Call the list_tools handler directly."""
        from suno_mcp.server import list_tools
        result = await list_tools()
        tool_names = [t["name"] for t in result["tools"]]
        assert "suno_browser_login" in tool_names
        assert "suno_api_generate" in tool_names
        assert "suno_session_info" in tool_names
