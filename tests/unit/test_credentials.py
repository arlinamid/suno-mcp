"""
Unit tests for credentials.py — secure storage, validation, cookie jar.
"""
import sys
import pathlib
import time
from unittest.mock import MagicMock, patch

import pytest

src = pathlib.Path(__file__).parents[2] / "src"
if str(src) not in sys.path:
    sys.path.insert(0, str(src))

from tests.conftest import make_fresh_jwt, make_expired_jwt, make_cookie_jar


# ── Helpers ───────────────────────────────────────────────────────────────────

def fresh_store():
    """Create an isolated CredentialStore backed by an in-memory dict."""
    from suno_mcp.tools.shared.credentials import CredentialStore, _EnvOnlyStore

    store = CredentialStore.__new__(CredentialStore)
    store._cached_cookie = None
    store._cached_token = None
    store._cached_jar = None

    # Use an in-memory backend to avoid touching the real OS keychain
    class _MemStore:
        backend_name = "MemoryStore"
        def __init__(self): self._data = {}
        def get(self, key): return self._data.get(key)
        def set(self, key, value): self._data[key] = value
        def delete(self, key):
            if key in self._data:
                del self._data[key]
                return True
            return False

    store._store = _MemStore()
    return store


# ── save_cookie_jar ───────────────────────────────────────────────────────────

class TestSaveCookieJar:
    def test_saves_valid_jar_with_client(self):
        store = fresh_store()
        jwt = make_fresh_jwt()
        jar = make_cookie_jar(jwt=jwt, include_client=True)
        result = store.save_cookie_jar(jar)
        assert "Full session saved" in result
        assert "HTTP-only __client captured : YES" in result
        assert jwt[:10] not in result  # JWT not echoed back raw

    def test_saves_valid_jar_without_client(self):
        store = fresh_store()
        jwt = make_fresh_jwt()
        jar = make_cookie_jar(jwt=jwt, include_client=False)
        result = store.save_cookie_jar(jar)
        assert "Full session saved" in result
        assert "browser fallback" in result

    def test_rejects_empty_dict(self):
        store = fresh_store()
        with pytest.raises(ValueError, match="non-empty"):
            store.save_cookie_jar({})

    def test_rejects_jar_without_session(self):
        store = fresh_store()
        with pytest.raises(ValueError, match="__session"):
            store.save_cookie_jar({"foo": "bar", "__client": "tok"})

    def test_persists_session_id(self):
        store = fresh_store()
        jwt = make_fresh_jwt()
        store.save_cookie_jar(make_cookie_jar(jwt=jwt))
        sid = store.get_session_id()
        assert sid == "session_test123"

    def test_preserves_existing_device_id(self):
        store = fresh_store()
        jar = make_cookie_jar()
        jar["suno_device_id"] = "my-custom-device-id"
        store.save_cookie_jar(jar)
        assert store._store.get("device_id") == "my-custom-device-id"


# ── get_cookie_jar ─────────────────────────────────────────────────────────────

class TestGetCookieJar:
    def test_returns_saved_jar(self):
        store = fresh_store()
        jar = make_cookie_jar()
        store.save_cookie_jar(jar)
        retrieved = store.get_cookie_jar()
        assert retrieved is not None
        assert "__session" in retrieved

    def test_returns_none_when_nothing_saved(self):
        store = fresh_store()
        assert store.get_cookie_jar() is None

    def test_handles_corrupted_json(self):
        store = fresh_store()
        store._store.set("full_cookie_jar", "this is not json{{{{")
        assert store.get_cookie_jar() is None


# ── update_session_token ───────────────────────────────────────────────────────

class TestUpdateSessionToken:
    def test_updates_jwt_preserves_client_cookie(self):
        store = fresh_store()
        old_jwt = make_fresh_jwt()
        new_jwt = make_fresh_jwt()
        jar = make_cookie_jar(jwt=old_jwt, include_client=True)
        store.save_cookie_jar(jar)

        store.update_session_token(new_jwt)

        updated = store.get_cookie_jar()
        assert updated["__session"] == new_jwt
        assert "__client" in updated  # preserved!

    def test_updates_legacy_cookie_string(self):
        store = fresh_store()
        old_jwt = make_fresh_jwt()
        new_jwt = make_fresh_jwt()
        store.save_cookie_jar(make_cookie_jar(jwt=old_jwt))

        store.update_session_token(new_jwt)

        cookie_str = store._store.get("session_cookie")
        assert new_jwt in cookie_str

    def test_rejects_invalid_token(self):
        store = fresh_store()
        store.save_cookie_jar(make_cookie_jar())
        with pytest.raises(Exception):
            store.update_session_token("not-a-jwt")


# ── get_current_jwt ────────────────────────────────────────────────────────────

class TestGetCurrentJwt:
    def test_returns_jwt_from_jar(self):
        store = fresh_store()
        jwt = make_fresh_jwt()
        store.save_cookie_jar(make_cookie_jar(jwt=jwt))
        assert store.get_current_jwt() == jwt

    def test_falls_back_to_legacy_cookie(self):
        store = fresh_store()
        jwt = make_fresh_jwt()
        store._store.set("session_cookie", f"__session={jwt}")
        result = store.get_current_jwt()
        assert result == jwt

    def test_returns_none_when_nothing_set(self):
        store = fresh_store()
        assert store.get_current_jwt() is None


# ── save_cookie / save_token (legacy) ────────────────────────────────────────

class TestLegacyCookieSave:
    def test_save_valid_cookie_string(self):
        store = fresh_store()
        jwt = make_fresh_jwt()
        result = store.save_cookie(f"__session={jwt}")
        assert "Credential saved" in result
        assert jwt not in result  # secret not echoed

    def test_save_valid_token(self):
        store = fresh_store()
        jwt = make_fresh_jwt()
        result = store.save_token(jwt)
        assert "Credential saved" in result

    def test_rejects_short_token(self):
        store = fresh_store()
        with pytest.raises(ValueError):
            store.save_token("short")

    def test_rejects_token_without_dots(self):
        store = fresh_store()
        with pytest.raises(ValueError):
            store.save_token("a" * 50)  # no dots → not a JWT


# ── clear ─────────────────────────────────────────────────────────────────────

class TestClear:
    def test_clears_all_stored_data(self):
        store = fresh_store()
        jwt = make_fresh_jwt()
        store.save_cookie_jar(make_cookie_jar(jwt=jwt))
        store.save_token(jwt)

        result = store.clear()
        assert "Cleared" in result
        assert store.get_cookie_jar() is None
        assert store.get_current_jwt() is None

    def test_clear_when_nothing_stored(self):
        store = fresh_store()
        result = store.clear()
        assert "No stored credentials" in result


# ── status ────────────────────────────────────────────────────────────────────

class TestStatus:
    def test_status_unauthenticated(self):
        store = fresh_store()
        s = store.status()
        assert "Not authenticated" in s
        assert "suno_browser_login" in s

    def test_status_with_full_jar_with_client(self):
        store = fresh_store()
        jwt = make_fresh_jwt()
        store.save_cookie_jar(make_cookie_jar(jwt=jwt, include_client=True))
        s = store.status()
        assert "Full cookie jar" in s
        assert "Auto-refresh" in s
        assert "YES (HTTP)" in s
        assert "Valid" in s

    def test_status_with_jar_without_client(self):
        store = fresh_store()
        store.save_cookie_jar(make_cookie_jar(include_client=False))
        s = store.status()
        assert "browser fallback" in s

    def test_status_never_reveals_raw_jwt(self):
        store = fresh_store()
        jwt = make_fresh_jwt()
        store.save_cookie_jar(make_cookie_jar(jwt=jwt))
        s = store.status()
        assert jwt not in s


# ── get_device_id ─────────────────────────────────────────────────────────────

class TestGetDeviceId:
    def test_generates_and_stores_uuid(self):
        store = fresh_store()
        device_id = store.get_device_id()
        assert len(device_id) == 36  # UUID format
        assert device_id.count("-") == 4

    def test_returns_same_id_on_second_call(self):
        store = fresh_store()
        id1 = store.get_device_id()
        id2 = store.get_device_id()
        assert id1 == id2

    def test_uses_env_var_when_available(self, monkeypatch):
        monkeypatch.setenv("SUNO_DEVICE_ID", "env-device-id-from-test")
        store = fresh_store()
        assert store.get_device_id() == "env-device-id-from-test"
        monkeypatch.delenv("SUNO_DEVICE_ID", raising=False)
