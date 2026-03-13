"""
Unit tests for session_manager.py — JWT lifecycle, expiry, refresh logic.
"""
import asyncio
import base64
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import (
    make_jwt,
    make_fresh_jwt,
    make_expired_jwt,
    make_expiring_soon_jwt,
    make_cookie_jar,
    FRESH_JWT,
    EXPIRED_JWT,
)


@pytest.fixture(autouse=True)
def import_module():
    """Ensure module is importable."""
    import sys, pathlib
    src = pathlib.Path(__file__).parents[2] / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))


# ── decode_jwt_payload ─────────────────────────────────────────────────────────

class TestDecodeJwtPayload:
    def setup_method(self):
        from suno_mcp.tools.shared.session_manager import decode_jwt_payload
        self.decode = decode_jwt_payload

    def test_decodes_valid_jwt(self, fresh_jwt):
        payload = self.decode(fresh_jwt)
        assert "suno.com/claims/user_id" in payload
        assert payload["suno.com/claims/user_id"] == "test-user-123"
        assert "sid" in payload
        assert "exp" in payload

    def test_raises_on_non_jwt_string(self):
        with pytest.raises(ValueError, match="3 parts"):
            self.decode("not.a.valid.jwt.at.all.extra")

    def test_raises_on_empty_string(self):
        with pytest.raises(ValueError):
            self.decode("")

    def test_handles_padding_variants(self):
        """JWT base64 parts may need padding — should handle silently."""
        # Just verify it doesn't crash on the real-world-style JWT
        payload = self.decode(make_jwt())
        assert payload.get("iss") == "https://auth.suno.com"


# ── get_token_expiry ───────────────────────────────────────────────────────────

class TestGetTokenExpiry:
    def setup_method(self):
        from suno_mcp.tools.shared.session_manager import get_token_expiry
        self.get_expiry = get_token_expiry

    def test_returns_datetime_for_valid_token(self, fresh_jwt):
        from datetime import datetime, timezone
        expiry = self.get_expiry(fresh_jwt)
        assert expiry is not None
        assert isinstance(expiry, datetime)
        assert expiry.tzinfo == timezone.utc

    def test_returns_none_for_garbage(self):
        result = self.get_expiry("garbage")
        assert result is None


# ── is_token_expired ──────────────────────────────────────────────────────────

class TestIsTokenExpired:
    def setup_method(self):
        from suno_mcp.tools.shared.session_manager import is_token_expired
        self.is_expired = is_token_expired

    def test_fresh_token_not_expired(self, fresh_jwt):
        assert self.is_expired(fresh_jwt, buffer_seconds=0) is False

    def test_expired_token_is_expired(self, expired_jwt):
        assert self.is_expired(expired_jwt, buffer_seconds=0) is True

    def test_expiring_soon_flagged_with_buffer(self, expiring_soon_jwt):
        # expires in 60s, buffer is 5 min (300s) — should be flagged
        assert self.is_expired(expiring_soon_jwt, buffer_seconds=300) is True

    def test_expiring_soon_ok_without_buffer(self, expiring_soon_jwt):
        # expires in 60s, no buffer — still valid
        assert self.is_expired(expiring_soon_jwt, buffer_seconds=0) is False

    def test_returns_true_for_garbage_token(self):
        assert self.is_expired("not.a.token") is True


# ── get_session_id ─────────────────────────────────────────────────────────────

class TestGetSessionId:
    def setup_method(self):
        from suno_mcp.tools.shared.session_manager import get_session_id
        self.get_sid = get_session_id

    def test_extracts_session_id(self, fresh_jwt):
        sid = self.get_sid(fresh_jwt)
        assert sid == "session_test123"

    def test_returns_none_for_garbage(self):
        assert self.get_sid("garbage") is None


# ── token_claims_summary ──────────────────────────────────────────────────────

class TestTokenClaimsSummary:
    def setup_method(self):
        from suno_mcp.tools.shared.session_manager import token_claims_summary
        self.summary = token_claims_summary

    def test_contains_expected_fields(self, fresh_jwt):
        s = self.summary(fresh_jwt)
        assert "Issued" in s
        assert "Expires" in s
        assert "TTL" in s
        assert "test@example.com" in s
        assert "session_test123" in s

    def test_shows_expired_for_old_token(self, expired_jwt):
        s = self.summary(expired_jwt)
        assert "EXPIRED" in s

    def test_does_not_contain_raw_jwt(self, fresh_jwt):
        s = self.summary(fresh_jwt)
        # Summary must not echo the full JWT back
        assert fresh_jwt not in s

    def test_graceful_on_bad_input(self):
        s = self.summary("bad_token")
        assert "Could not decode" in s


# ── extract_session_from_cookies ─────────────────────────────────────────────

class TestExtractSessionFromCookies:
    def setup_method(self):
        from suno_mcp.tools.shared.session_manager import extract_session_from_cookies
        self.extract = extract_session_from_cookies

    def test_extracts_base_session(self, fresh_jwt):
        jar = {"__session": fresh_jwt, "other": "cookie"}
        assert self.extract(jar) == fresh_jwt

    def test_falls_back_to_suffixed(self, fresh_jwt):
        jar = {"__session_Jnxw-muT": fresh_jwt}
        assert self.extract(jar) == fresh_jwt

    def test_prefers_base_over_suffixed(self, fresh_jwt, expired_jwt):
        jar = {"__session": fresh_jwt, "__session_Jnxw-muT": expired_jwt}
        assert self.extract(jar) == fresh_jwt

    def test_returns_none_for_empty(self):
        assert self.extract({}) is None


# ── build_cookie_header ───────────────────────────────────────────────────────

class TestBuildCookieHeader:
    def setup_method(self):
        from suno_mcp.tools.shared.session_manager import build_cookie_header
        self.build = build_cookie_header

    def test_builds_valid_header(self):
        jar = {"a": "1", "b": "2"}
        header = self.build(jar)
        assert "a=1" in header
        assert "b=2" in header
        assert header.count(";") == 1

    def test_single_cookie(self):
        assert self.build({"x": "y"}) == "x=y"


# ── cookies_from_playwright ───────────────────────────────────────────────────

class TestCookiesFromPlaywright:
    def setup_method(self):
        from suno_mcp.tools.shared.session_manager import cookies_from_playwright
        self.from_pw = cookies_from_playwright

    def test_filters_suno_domain(self, fresh_jwt):
        pw_cookies = [
            {"name": "__session", "value": fresh_jwt, "domain": ".suno.com"},
            {"name": "other", "value": "val", "domain": ".google.com"},
            {"name": "__client", "value": "tok", "domain": "auth.suno.com"},
        ]
        result = self.from_pw(pw_cookies)
        assert "__session" in result
        assert "__client" in result
        assert "other" not in result

    def test_empty_input(self):
        assert self.from_pw([]) == {}


# ── ClerkTokenRefresher ───────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestClerkTokenRefresher:
    def setup_method(self):
        from suno_mcp.tools.shared.session_manager import ClerkTokenRefresher
        self.RefresherClass = ClerkTokenRefresher

    async def test_http_refresh_success(self, fresh_jwt, cookie_jar_with_client):
        """Successful HTTP refresh returns the new JWT from response body."""
        new_jwt = make_jwt(exp_offset=7200, session_id="session_test123")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"jwt": new_jwt}

        refresher = self.RefresherClass()
        with patch.object(refresher, "_get_http_client") as mock_client_fn:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_fn.return_value = mock_client

            result = await refresher.refresh_via_http("session_test123", cookie_jar_with_client)

        assert result == new_jwt

    async def test_http_refresh_401_returns_none(self, cookie_jar_with_client):
        """HTTP 401 → returns None (session expired, re-login needed)."""
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = '{"errors": [{"code": "session_expired"}]}'

        refresher = self.RefresherClass()
        with patch.object(refresher, "_get_http_client") as mock_client_fn:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_fn.return_value = mock_client

            result = await refresher.refresh_via_http("session_test123", cookie_jar_with_client)

        assert result is None

    async def test_http_refresh_network_error_returns_none(self, cookie_jar_with_client):
        """Network errors don't propagate — returns None."""
        import httpx
        refresher = self.RefresherClass()
        with patch.object(refresher, "_get_http_client") as mock_client_fn:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=httpx.ConnectError("conn refused"))
            mock_client_fn.return_value = mock_client

            result = await refresher.refresh_via_http("session_test123", cookie_jar_with_client)

        assert result is None

    async def test_missing_session_id_returns_none(self, cookie_jar_with_client):
        refresher = self.RefresherClass()
        result = await refresher.refresh_via_http("", cookie_jar_with_client)
        assert result is None
