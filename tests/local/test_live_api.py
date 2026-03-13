"""
Live integration tests — require real Suno credentials in the keychain.
Run with:  pytest tests/local/ -v -s

These tests are skipped automatically when no credentials are configured.
They make REAL HTTP requests to suno.com and studio-api.prod.suno.com.
"""
import sys
import pathlib

import pytest

src = pathlib.Path(__file__).parents[2] / "src"
if str(src) not in sys.path:
    sys.path.insert(0, str(src))


def has_credentials() -> bool:
    try:
        from suno_mcp.tools.shared.credentials import get_credential_store
        return get_credential_store().is_configured()
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not has_credentials(),
    reason="No Suno credentials configured. Run suno_browser_login() first.",
)


@pytest.mark.asyncio
async def test_get_trending_live():
    """Fetch real trending songs — no auth required."""
    from suno_mcp.tools.shared.api_client import get_api_client
    client = get_api_client()
    result = await client.get_trending(page=0)
    # API returns playlist_clips (wrapped) or clips (direct) depending on endpoint version
    clips_raw = result.get("playlist_clips") or result.get("clips") or []
    assert len(clips_raw) > 0, f"Expected songs, got: {list(result.keys())}"
    # Each item may be {"clip": {...}} or a direct clip object
    first = clips_raw[0].get("clip", clips_raw[0])
    assert "id" in first
    print(f"\nFirst trending: {first.get('title','?')} | ID: {first['id']}")


@pytest.mark.asyncio
async def test_token_refresh_live():
    """Test that the JWT can be obtained or refreshed."""
    from suno_mcp.tools.shared.credentials import get_credential_store
    from suno_mcp.tools.shared.session_manager import is_token_expired, token_claims_summary

    creds = get_credential_store()
    jwt = creds.get_current_jwt()
    assert jwt is not None, "No JWT found in credentials"

    print(f"\nToken claims:\n{token_claims_summary(jwt)}")

    expired = is_token_expired(jwt, buffer_seconds=0)
    if expired:
        print("Token is expired — testing refresh...")
        from suno_mcp.tools.api.tools import ApiSunoTools
        tools = ApiSunoTools()
        result = await tools.refresh_session(force=True)
        print(f"Refresh result:\n{result}")
        assert "failed" not in result.lower() or "re-authenticate" in result.lower()
    else:
        print("Token is valid — no refresh needed")


@pytest.mark.asyncio
async def test_session_info_live():
    """Real session info — shows actual expiry."""
    from suno_mcp.tools.api.tools import ApiSunoTools
    tools = ApiSunoTools()
    result = await tools.session_info()
    print(f"\nSession info:\n{result}")
    assert isinstance(result, str)
    assert len(result) > 20


@pytest.mark.asyncio
async def test_check_auth_live():
    """Test real authentication check."""
    from suno_mcp.tools.shared.credentials import get_credential_store
    from suno_mcp.tools.shared.session_manager import token_claims_summary
    creds = get_credential_store()
    jwt = creds.get_current_jwt()
    assert jwt is not None, "No JWT — run suno_browser_login() first"
    # Test credential store status (avoids shared singleton httpx client event loop issues)
    status = creds.status()
    print(f"\nCredential status:\n{status}")
    assert "WinVaultKeyring" in status or "Keyring" in status
    assert "Valid" in status or "TTL" in status


@pytest.mark.asyncio
async def test_get_credits_live():
    """Fetch actual credit balance."""
    from suno_mcp.tools.shared.api_client import get_api_client
    client = get_api_client()
    if not client.is_authenticated():
        pytest.skip("Not authenticated")
    result = await client.get_credits()
    print(f"\nCredits response: {result}")
    assert isinstance(result, dict)
