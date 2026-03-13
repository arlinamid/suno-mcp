"""
Unit tests for api_client.py — HTTP calls, auth headers, auto-refresh.
"""
import json
import sys
import pathlib
import time
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import httpx
import pytest

src = pathlib.Path(__file__).parents[2] / "src"
if str(src) not in sys.path:
    sys.path.insert(0, str(src))

from tests.conftest import make_fresh_jwt, make_expired_jwt, make_cookie_jar


# ── Helpers ────────────────────────────────────────────────────────────────────

def make_mock_response(status: int = 200, body: Any = None):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    if body is None:
        body = {}
    resp.json.return_value = body
    resp.text = json.dumps(body)
    return resp


# ── _make_browser_token ───────────────────────────────────────────────────────

class TestMakeBrowserToken:
    def test_returns_base64_string(self):
        import base64
        from suno_mcp.tools.shared.api_client import _make_browser_token
        token = _make_browser_token()
        decoded = json.loads(base64.b64decode(token + "=="))
        assert "timestamp" in decoded
        assert isinstance(decoded["timestamp"], int)


# ── SunoApiClient init / singleton ───────────────────────────────────────────

class TestSunoApiClientInit:
    def test_get_api_client_returns_singleton(self):
        from suno_mcp.tools.shared.api_client import get_api_client
        c1 = get_api_client()
        c2 = get_api_client()
        assert c1 is c2

    def test_device_id_is_uuid_format(self):
        from suno_mcp.tools.shared.api_client import get_api_client
        client = get_api_client()
        assert len(client._device_id) == 36
        assert client._device_id.count("-") == 4


# ── _get_auth_headers ─────────────────────────────────────────────────────────

class TestGetAuthHeaders:
    def _make_client_with_jar(self, jwt: str, include_client: bool = True):
        from suno_mcp.tools.shared.api_client import SunoApiClient
        client = object.__new__(SunoApiClient)
        client._device_id = "test-device-id"
        client._http_client = None

        # Build a fresh in-memory CredentialStore
        from tests.unit.test_credentials import fresh_store
        store = fresh_store()
        store.save_cookie_jar(make_cookie_jar(jwt=jwt, include_client=include_client))
        client._creds = store
        return client

    def test_includes_authorization_bearer(self):
        jwt = make_fresh_jwt()
        client = self._make_client_with_jar(jwt)
        headers = client._get_auth_headers()
        assert "Authorization" in headers
        assert headers["Authorization"] == f"Bearer {jwt}"

    def test_includes_device_id(self):
        client = self._make_client_with_jar(make_fresh_jwt())
        headers = client._get_auth_headers()
        assert headers["device-id"] == "test-device-id"

    def test_includes_browser_token(self):
        client = self._make_client_with_jar(make_fresh_jwt())
        headers = client._get_auth_headers()
        assert "browser-token" in headers

    def test_includes_full_cookie_header(self):
        jwt = make_fresh_jwt()
        client = self._make_client_with_jar(jwt)
        headers = client._get_auth_headers()
        assert "Cookie" in headers
        assert f"__session={jwt}" in headers["Cookie"]

    def test_no_auth_when_unauthenticated(self):
        from suno_mcp.tools.shared.api_client import SunoApiClient
        from tests.unit.test_credentials import fresh_store
        client = object.__new__(SunoApiClient)
        client._device_id = "test-device-id"
        client._http_client = None
        client._creds = fresh_store()
        headers = client._get_auth_headers()
        assert "Authorization" not in headers
        assert "Cookie" not in headers


# ── _check_response ───────────────────────────────────────────────────────────

class TestCheckResponse:
    def _client(self):
        from suno_mcp.tools.shared.api_client import SunoApiClient
        from tests.unit.test_credentials import fresh_store
        c = object.__new__(SunoApiClient)
        c._device_id = "x"
        c._http_client = None
        c._creds = fresh_store()
        return c

    def test_200_passes_silently(self):
        self._client()._check_response(make_mock_response(200))

    def test_401_raises_auth_error(self):
        from suno_mcp.tools.shared.exceptions import SunoError
        with pytest.raises(SunoError) as exc_info:
            self._client()._check_response(make_mock_response(401))
        assert exc_info.value.code == "AUTH_REQUIRED"

    def test_403_raises_forbidden(self):
        from suno_mcp.tools.shared.exceptions import SunoError
        with pytest.raises(SunoError) as exc_info:
            self._client()._check_response(make_mock_response(403))
        assert exc_info.value.code == "FORBIDDEN"

    def test_429_raises_rate_limited(self):
        from suno_mcp.tools.shared.exceptions import SunoError
        with pytest.raises(SunoError) as exc_info:
            self._client()._check_response(make_mock_response(429))
        assert exc_info.value.code == "RATE_LIMITED"

    def test_500_raises_api_error(self):
        from suno_mcp.tools.shared.exceptions import SunoError
        with pytest.raises(SunoError) as exc_info:
            self._client()._check_response(
                make_mock_response(500, {"detail": "Internal server error"})
            )
        assert exc_info.value.code == "API_ERROR"


# ── _ensure_fresh_token ───────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestEnsureFreshToken:
    def _client_with_expired_token(self):
        from suno_mcp.tools.shared.api_client import SunoApiClient
        from tests.unit.test_credentials import fresh_store
        c = object.__new__(SunoApiClient)
        c._device_id = "x"
        c._http_client = None
        c._creds = fresh_store()
        expired_jwt = make_expired_jwt()
        c._creds.save_cookie_jar(make_cookie_jar(jwt=expired_jwt, include_client=True))
        return c

    def _client_with_fresh_token(self):
        from suno_mcp.tools.shared.api_client import SunoApiClient
        from tests.unit.test_credentials import fresh_store
        c = object.__new__(SunoApiClient)
        c._device_id = "x"
        c._http_client = None
        c._creds = fresh_store()
        c._creds.save_cookie_jar(make_cookie_jar(jwt=make_fresh_jwt(), include_client=True))
        return c

    async def test_skips_refresh_when_token_fresh(self):
        """No refresh call should happen when token is still valid."""
        client = self._client_with_fresh_token()
        with patch("suno_mcp.tools.shared.api_client.get_refresher") as mock_get:
            await client._ensure_fresh_token()
            mock_get.assert_not_called()

    async def test_triggers_http_refresh_when_expired(self):
        """When token is expired and __client cookie present → HTTP refresh."""
        client = self._client_with_expired_token()
        new_jwt = make_fresh_jwt()
        mock_refresher = AsyncMock()
        mock_refresher.refresh_via_http = AsyncMock(return_value=new_jwt)

        with patch("suno_mcp.tools.shared.api_client.get_refresher", return_value=mock_refresher):
            await client._ensure_fresh_token()

        mock_refresher.refresh_via_http.assert_called_once()
        # Token should now be updated
        assert client._creds.get_current_jwt() == new_jwt

    async def test_falls_back_to_playwright_when_http_fails(self):
        """If HTTP refresh returns None → try browser fallback."""
        client = self._client_with_expired_token()
        new_jwt = make_fresh_jwt()
        mock_refresher = AsyncMock()
        mock_refresher.refresh_via_http = AsyncMock(return_value=None)
        mock_refresher.refresh_via_playwright = AsyncMock(return_value=(new_jwt, make_cookie_jar(jwt=new_jwt)))

        with patch("suno_mcp.tools.shared.api_client.get_refresher", return_value=mock_refresher):
            await client._ensure_fresh_token()

        mock_refresher.refresh_via_playwright.assert_called_once()


# ── is_authenticated ──────────────────────────────────────────────────────────

class TestIsAuthenticated:
    def test_false_when_no_credentials(self):
        from suno_mcp.tools.shared.api_client import SunoApiClient
        from tests.unit.test_credentials import fresh_store
        c = object.__new__(SunoApiClient)
        c._device_id = "x"
        c._http_client = None
        c._creds = fresh_store()
        assert c.is_authenticated() is False

    def test_true_when_jar_saved(self):
        from suno_mcp.tools.shared.api_client import SunoApiClient
        from tests.unit.test_credentials import fresh_store
        c = object.__new__(SunoApiClient)
        c._device_id = "x"
        c._http_client = None
        c._creds = fresh_store()
        c._creds.save_cookie_jar(make_cookie_jar())
        assert c.is_authenticated() is True
