"""
Secure credential storage for Suno MCP.

Stores ALL Suno session data in the OS-native credential vault:
  - Windows : Windows Credential Manager  (WinVaultKeyring)
  - macOS   : Keychain
  - Linux   : libsecret / KWallet

Stored items:
  session_cookie   — legacy: __session=<jwt> string (env-var style)
  auth_token       — legacy: raw Bearer JWT
  full_cookie_jar  — JSON dict of ALL cookies captured by Playwright login
                     (includes HTTP-only __client needed for refresh)
  session_id       — Clerk session ID (e.g. session_c15fcdb...)
  device_id        — Persistent device UUID

Env-var fallback is supported for CI/headless environments, but env vars
are NEVER written by this module.

Security properties:
  • Credentials never written to disk in plaintext
  • Token values never logged or included in exceptions
  • Memory cleared on logout via explicit wipe
  • Input validation rejects malformed tokens before storage
"""

import hashlib
import json
import logging
import os
import pathlib
import re
import secrets
from typing import Dict, Optional

try:
    import keyring
    import keyring.errors as keyring_errors
    _KEYRING_AVAILABLE = True
except ImportError:
    _KEYRING_AVAILABLE = False

logger = logging.getLogger(__name__)

_SERVICE = "suno-mcp"
_COOKIE_KEY = "session_cookie"       # legacy: __session=<jwt> string
_TOKEN_KEY = "auth_token"            # legacy: raw Bearer JWT
_DEVICE_KEY = "device_id"            # persistent device UUID
_JAR_KEY = "full_cookie_jar"         # JSON dict of all cookies (from Playwright)
_SESSION_ID_KEY = "clerk_session_id" # Clerk session ID for token refresh


# ── Validation ────────────────────────────────────────────────────────────────

_JWT_RE = re.compile(r'^[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]*$')
_COOKIE_RE = re.compile(r'__session=[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]*')


def _validate_token(token: str) -> None:
    """Raise ValueError if the token is not a valid-looking JWT."""
    if not token or len(token) < 20:
        raise ValueError("Token too short to be valid")
    if len(token) > 8192:
        raise ValueError("Token suspiciously long — refusing storage")
    if not _JWT_RE.match(token):
        raise ValueError(
            "Token does not look like a valid JWT (expected header.payload.signature)"
        )


def _validate_cookie(cookie: str) -> None:
    """Raise ValueError if the cookie string doesn't contain a valid __session."""
    if not cookie:
        raise ValueError("Cookie string is empty")
    if len(cookie) > 16384:
        raise ValueError("Cookie string suspiciously long — refusing storage")
    if not _COOKIE_RE.search(cookie):
        raise ValueError(
            "Cookie must contain '__session=<jwt>' — copy the __session cookie "
            "value from DevTools (Application → Cookies → suno.com)"
        )


def _mask(value: str) -> str:
    """Return a safe, non-reversible display version of a secret value."""
    if not value:
        return "<empty>"
    visible = min(8, len(value) // 6)
    digest = hashlib.sha256(value.encode()).hexdigest()[:8]
    return f"{value[:visible]}...{value[-4:]} (sha256:{digest})"


# ── Large-value encrypted file store ─────────────────────────────────────────
#
# Windows Credential Manager has a 2560-byte limit per credential. The full
# Suno cookie jar (with JWTs, ~5KB+) exceeds that. For large values we use
# Windows DPAPI-encrypted files in %APPDATA%\suno-mcp\ so the data is
# protected by the current user's Windows login — no separate key required.
# On macOS/Linux, the same path is used but with Fernet encryption, with the
# key stored in the keychain (key itself is only 44 bytes, fits easily).

_APPDATA_DIR = pathlib.Path(os.environ.get("APPDATA", os.path.expanduser("~"))) / "suno-mcp"
_LARGE_SIZE_THRESHOLD = 1800  # bytes — save via DPAPI/Fernet when value exceeds this


def _dpapi_encrypt(data: bytes) -> bytes:
    """Encrypt bytes with Windows DPAPI (tied to current user account)."""
    import win32crypt
    # pywin32 CryptProtectData signature varies by version — use minimal args
    result = win32crypt.CryptProtectData(data, None, None, None, None, 0)
    return result if isinstance(result, (bytes, bytearray)) else result[1]


def _dpapi_decrypt(data: bytes) -> bytes:
    """Decrypt bytes previously encrypted with Windows DPAPI."""
    import win32crypt
    # Try with 5 args first (most pywin32 versions), fall back to fewer
    try:
        result = win32crypt.CryptUnprotectData(data, None, None, None, 0)
    except TypeError:
        result = win32crypt.CryptUnprotectData(data)
    return result[1] if isinstance(result, tuple) else result


def _fernet_encrypt(data: bytes, key: bytes) -> bytes:
    from cryptography.fernet import Fernet
    return Fernet(key).encrypt(data)


def _fernet_decrypt(data: bytes, key: bytes) -> bytes:
    from cryptography.fernet import Fernet
    return Fernet(key).decrypt(data)


def _file_path(key: str) -> pathlib.Path:
    """Return the encrypted file path for a given credential key."""
    safe_key = key.replace("/", "_").replace("\\", "_")
    return _APPDATA_DIR / f"{safe_key}.bin"


def _save_large_value(key: str, value: str) -> None:
    """
    Persist a large credential value securely using DPAPI (Windows) or
    Fernet+keyring (other platforms). Falls back to plain keyring if neither
    platform-specific method is available.
    """
    _APPDATA_DIR.mkdir(parents=True, exist_ok=True)
    raw = value.encode("utf-8")
    path = _file_path(key)

    if os.name == "nt":
        try:
            encrypted = _dpapi_encrypt(raw)
            path.write_bytes(encrypted)
            logger.debug("Saved large credential '%s' via DPAPI (%d bytes)", key, len(encrypted))
            return
        except Exception as e:
            logger.warning("DPAPI encrypt failed (%s) — falling back to Fernet", e)

    # Non-Windows or DPAPI fallback: Fernet + keyring key
    try:
        from cryptography.fernet import Fernet
        fernet_key_name = f"_fernet_key_{key}"
        enc_key = None
        if _KEYRING_AVAILABLE:
            enc_key_str = keyring.get_password(_SERVICE, fernet_key_name)
            if enc_key_str:
                enc_key = enc_key_str.encode()
        if not enc_key:
            enc_key = Fernet.generate_key()
            if _KEYRING_AVAILABLE:
                keyring.set_password(_SERVICE, fernet_key_name, enc_key.decode())
        encrypted = _fernet_encrypt(raw, enc_key)
        path.write_bytes(encrypted)
        logger.debug("Saved large credential '%s' via Fernet (%d bytes)", key, len(encrypted))
    except Exception as e:
        logger.warning("Fernet encrypt failed (%s) — will attempt plain keyring", e)
        raise


def _load_large_value(key: str) -> Optional[str]:
    """Load and decrypt a value previously stored by _save_large_value."""
    path = _file_path(key)
    if not path.exists():
        return None

    encrypted = path.read_bytes()

    # Fernet tokens start with 'gA' when base64-decoded — skip DPAPI for those
    _is_fernet = encrypted[:2] == b"gA"

    if os.name == "nt" and not _is_fernet:
        try:
            raw = _dpapi_decrypt(encrypted)
            return raw.decode("utf-8")
        except Exception as e:
            logger.debug("DPAPI decrypt failed for '%s': %s — trying Fernet", key, e)

    # Fernet fallback
    try:
        from cryptography.fernet import Fernet
        fernet_key_name = f"_fernet_key_{key}"
        enc_key = None
        if _KEYRING_AVAILABLE:
            enc_key_str = keyring.get_password(_SERVICE, fernet_key_name)
            if enc_key_str:
                enc_key = enc_key_str.encode()
        if enc_key:
            return _fernet_decrypt(encrypted, enc_key).decode("utf-8")
    except Exception as e:
        logger.warning("Fernet decrypt failed for '%s': %s", key, e)

    return None


def _delete_large_value(key: str) -> bool:
    path = _file_path(key)
    if path.exists():
        path.unlink()
        # Also remove the Fernet key from keyring if present
        fernet_key_name = f"_fernet_key_{key}"
        if _KEYRING_AVAILABLE:
            try:
                keyring.delete_password(_SERVICE, fernet_key_name)
            except Exception:
                pass
        return True
    return False


# ── Storage back-ends ─────────────────────────────────────────────────────────

class _KeyringStore:
    """
    Stores credentials in the OS native credential vault via keyring.

    For values exceeding the Windows Credential Manager size limit (~2500 bytes),
    automatically uses DPAPI-encrypted files in %APPDATA%\\suno-mcp\\ instead.
    The files are tied to the current Windows user account — equally secure.
    """

    def set(self, key: str, value: str) -> None:
        if len(value.encode("utf-8")) > _LARGE_SIZE_THRESHOLD:
            _save_large_value(key, value)
        else:
            keyring.set_password(_SERVICE, key, value)

    def get(self, key: str) -> Optional[str]:
        # Check encrypted file first (large values)
        large = _load_large_value(key)
        if large is not None:
            return large
        # Fall back to keyring
        try:
            return keyring.get_password(_SERVICE, key)
        except keyring_errors.KeyringError:
            return None

    def delete(self, key: str) -> bool:
        deleted = _delete_large_value(key)
        try:
            keyring.delete_password(_SERVICE, key)
            deleted = True
        except (keyring_errors.PasswordDeleteError, keyring_errors.KeyringError):
            pass
        return deleted

    @property
    def backend_name(self) -> str:
        backend = type(keyring.get_keyring()).__name__
        return f"{backend}+DPAPI" if os.name == "nt" else backend


class _EnvOnlyStore:
    """Read-only fallback that only reads from env vars — never writes."""

    def set(self, key: str, value: str) -> None:
        raise RuntimeError(
            "keyring is not available. Install it with: pip install keyring\n"
            "Or set credentials via environment variables (SUNO_COOKIE / SUNO_AUTH_TOKEN)."
        )

    def get(self, key: str) -> Optional[str]:
        mapping = {
            _COOKIE_KEY: os.environ.get("SUNO_COOKIE"),
            _TOKEN_KEY: os.environ.get("SUNO_AUTH_TOKEN"),
        }
        return mapping.get(key)

    def delete(self, key: str) -> bool:
        return False

    @property
    def backend_name(self) -> str:
        return "EnvOnlyStore (keyring not installed)"


def _make_store() -> "_KeyringStore | _EnvOnlyStore":
    if _KEYRING_AVAILABLE:
        return _KeyringStore()
    return _EnvOnlyStore()


# ── Public API ────────────────────────────────────────────────────────────────

class CredentialStore:
    """
    Secure credential manager for Suno session data.

    Stores the full Playwright cookie jar so the MCP can silently refresh
    the __session JWT when it expires (via Clerk HTTP API or headless browser).

    Priority order when resolving a credential:
      1. OS keychain  — saved via suno_browser_login / suno_save_cookie
      2. SUNO_COOKIE / SUNO_AUTH_TOKEN environment variable (CI / Docker)
      3. Nothing → unauthenticated

    Secrets are NEVER logged. Only masked fingerprints are emitted.
    """

    def __init__(self) -> None:
        self._store = _make_store()
        self._cached_cookie: Optional[str] = None
        self._cached_token: Optional[str] = None
        self._cached_jar: Optional[Dict[str, str]] = None

    # ── Full cookie jar (primary — from Playwright browser login) ────────────

    def save_cookie_jar(self, jar: Dict[str, str]) -> str:
        """
        Securely persist the complete browser cookie jar captured by Playwright.

        This is the richest form of credentials — includes the HTTP-only
        __client cookie that enables silent JWT refresh via the Clerk API.

        Args:
            jar: dict of cookie name → value captured from suno.com domain

        Returns a human-readable confirmation (never the secrets themselves).
        """
        if not isinstance(jar, dict) or not jar:
            raise ValueError("Cookie jar must be a non-empty dict")

        # Must contain at least one session cookie
        has_session = any(k.startswith("__session") for k in jar)
        if not has_session:
            raise ValueError("Cookie jar must contain a __session cookie")

        raw = json.dumps(jar)
        self._store.set(_JAR_KEY, raw)
        self._cached_jar = jar

        # Also extract and cache __session / __client_uat for quick access
        session_token = jar.get("__session") or next(
            (v for k, v in jar.items() if k.startswith("__session_")), None
        )
        if session_token:
            self._store.set(_COOKIE_KEY, f"__session={session_token}")
            self._cached_cookie = f"__session={session_token}"

        session_id = None
        if session_token:
            try:
                from .session_manager import get_session_id
                session_id = get_session_id(session_token)
            except Exception:
                pass
        if session_id:
            self._store.set(_SESSION_ID_KEY, session_id)

        # Preserve the suno_device_id from the browser if it differs
        if "suno_device_id" in jar:
            stored_id = self._store.get(_DEVICE_KEY)
            if not stored_id:
                self._store.set(_DEVICE_KEY, jar["suno_device_id"])

        cookie_count = len(jar)
        has_client = "__client" in jar
        logger.info("Saved full cookie jar (%d cookies, __client=%s) to %s",
                    cookie_count, has_client, self._store.backend_name)
        return (
            f"Full session saved to {self._store.backend_name}\n"
            f"Cookies stored : {cookie_count}\n"
            f"HTTP-only __client captured : {'YES (refresh will work!)' if has_client else 'NO (refresh will use browser fallback)'}\n"
            f"Session ID : {session_id or 'unknown'}\n"
            f"Token fingerprint : {_mask(session_token) if session_token else 'none'}"
        )

    def get_cookie_jar(self) -> Optional[Dict[str, str]]:
        """Return the full stored cookie dict, or None if not available."""
        if self._cached_jar:
            return self._cached_jar
        raw = self._store.get(_JAR_KEY)
        if raw:
            try:
                self._cached_jar = json.loads(raw)
                return self._cached_jar
            except json.JSONDecodeError:
                logger.warning("Stored cookie jar is corrupted — ignoring")
        return None

    def update_session_token(self, new_jwt: str, updated_jar: Optional[Dict[str, str]] = None) -> None:
        """
        Update only the __session JWT after a successful token refresh.
        Preserves all other cookies in the jar (especially __client).
        """
        _validate_token(new_jwt)

        jar = updated_jar or self.get_cookie_jar() or {}

        # Update __session in the jar
        jar["__session"] = new_jwt
        # Also update any __session_<suffix> variants
        for key in list(jar.keys()):
            if key.startswith("__session_"):
                jar[key] = new_jwt

        self._store.set(_JAR_KEY, json.dumps(jar))
        self._cached_jar = jar

        # Update quick-access cookie string
        cookie_str = f"__session={new_jwt}"
        self._store.set(_COOKIE_KEY, cookie_str)
        self._cached_cookie = cookie_str

        # Update stored session ID
        try:
            from .session_manager import get_session_id
            sid = get_session_id(new_jwt)
            if sid:
                self._store.set(_SESSION_ID_KEY, sid)
        except Exception:
            pass

        logger.info("__session JWT updated after refresh")

    def get_session_id(self) -> Optional[str]:
        """Return the stored Clerk session ID for use in token refresh calls."""
        stored = self._store.get(_SESSION_ID_KEY)
        if stored:
            return stored
        # Try to extract it from the current token
        token = self.get_current_jwt()
        if token:
            try:
                from .session_manager import get_session_id
                return get_session_id(token)
            except Exception:
                pass
        return None

    def get_current_jwt(self) -> Optional[str]:
        """
        Return the current __session JWT from the stored cookie jar or legacy fields.
        Resolves: full_jar → legacy_cookie → env var → auth_token env var.
        """
        # 1. Full cookie jar (preferred)
        jar = self.get_cookie_jar()
        if jar:
            from .session_manager import extract_session_from_cookies
            token = extract_session_from_cookies(jar)
            if token:
                return token

        # 2. Legacy __session=<jwt> cookie string
        cookie = self.get_cookie()
        if cookie:
            for part in cookie.split(";"):
                part = part.strip()
                if part.startswith("__session="):
                    return part[len("__session="):]

        # 3. Raw token env var / legacy token
        return self.get_token()

    # ── Legacy single-value methods (still supported) ────────────────────────

    def save_cookie(self, cookie: str) -> str:
        """Save a __session=<jwt> cookie string (simpler alternative to full jar)."""
        _validate_cookie(cookie.strip())
        clean = cookie.strip()
        self._store.set(_COOKIE_KEY, clean)
        self._cached_cookie = clean
        logger.info("Saved Suno session cookie to %s", self._store.backend_name)
        return (
            f"Credential saved to {self._store.backend_name}\n"
            f"Fingerprint: {_mask(clean)}\n"
            f"Note: Use suno_browser_login() to capture the full cookie jar\n"
            f"      (needed for automatic JWT refresh when token expires)"
        )

    def save_token(self, token: str) -> str:
        """Save a raw JWT bearer token."""
        _validate_token(token.strip())
        clean = token.strip()
        self._store.set(_TOKEN_KEY, clean)
        self._cached_token = clean
        logger.info("Saved Suno auth token to %s", self._store.backend_name)
        return (
            f"Credential saved to {self._store.backend_name}\n"
            f"Fingerprint: {_mask(clean)}\n"
            f"Note: Token expires in ~60 minutes. Use suno_browser_login() for\n"
            f"      automatic refresh."
        )

    def get_cookie(self) -> Optional[str]:
        """Return the legacy __session=<jwt> cookie string."""
        if self._cached_cookie:
            return self._cached_cookie
        value = self._store.get(_COOKIE_KEY) or os.environ.get("SUNO_COOKIE")
        if value:
            self._cached_cookie = value
        return value

    def get_token(self) -> Optional[str]:
        """Return the legacy raw bearer token."""
        if self._cached_token:
            return self._cached_token
        value = self._store.get(_TOKEN_KEY) or os.environ.get("SUNO_AUTH_TOKEN")
        if value:
            self._cached_token = value
        return value

    def is_configured(self) -> bool:
        """True if any credential is available."""
        return bool(
            self.get_cookie_jar()
            or self.get_cookie()
            or self.get_token()
        )

    def clear(self) -> str:
        """Remove all stored credentials from the OS keychain and memory."""
        deleted: list[str] = []
        for key, label in [
            (_COOKIE_KEY, "session cookie"),
            (_TOKEN_KEY, "auth token"),
            (_JAR_KEY, "full cookie jar"),
            (_SESSION_ID_KEY, "session ID"),
        ]:
            if self._store.delete(key):
                deleted.append(label)
        self._wipe_cache()
        if deleted:
            return f"Cleared from {self._store.backend_name}: {', '.join(deleted)}"
        return "No stored credentials found."

    def status(self) -> str:
        """Return a safe (non-secret) status description."""
        from .session_manager import token_claims_summary, is_token_expired

        lines = [f"Backend   : {self._store.backend_name}"]

        jar = self.get_cookie_jar()
        if jar:
            has_client = "__client" in jar
            session_token = jar.get("__session")
            lines.append(f"Login method : Full cookie jar ({len(jar)} cookies)")
            lines.append(f"Auto-refresh : {'YES (HTTP)' if has_client else 'YES (browser fallback)'}")
            if session_token:
                try:
                    expired = is_token_expired(session_token, buffer_seconds=0)
                    lines.append(f"Token status : {'EXPIRED ⚠️' if expired else 'Valid ✅'}")
                    lines.append(token_claims_summary(session_token))
                except Exception:
                    pass
        else:
            cookie = self.get_cookie()
            token = self.get_token()
            if cookie:
                lines.append(f"Login method : Cookie string")
                lines.append(f"Auto-refresh : NO (no __client cookie — run suno_browser_login)")
                jwt = None
                for p in cookie.split(";"):
                    p = p.strip()
                    if p.startswith("__session="):
                        jwt = p[len("__session="):]
                if jwt:
                    try:
                        expired = is_token_expired(jwt, buffer_seconds=0)
                        lines.append(f"Token status : {'EXPIRED ⚠️' if expired else 'Valid ✅'}")
                        lines.append(token_claims_summary(jwt))
                    except Exception:
                        pass
            elif token:
                lines.append(f"Login method : Bearer token")
                lines.append(f"Auto-refresh : NO (run suno_browser_login for automatic refresh)")
                try:
                    expired = is_token_expired(token, buffer_seconds=0)
                    lines.append(f"Token status : {'EXPIRED ⚠️' if expired else 'Valid ✅'}")
                    lines.append(token_claims_summary(token))
                except Exception:
                    pass
            else:
                lines.append("Status       : Not authenticated")
                lines.append("→ Run suno_browser_login() to log in")

        return "\n".join(lines)

    # ── Device ID ─────────────────────────────────────────────────────────────

    def get_device_id(self) -> str:
        """Return a stable device UUID, generating and persisting one if needed."""
        stored = self._store.get(_DEVICE_KEY) if _KEYRING_AVAILABLE else None
        env_val = os.environ.get("SUNO_DEVICE_ID")
        if stored:
            return stored
        if env_val:
            return env_val
        # Generate a cryptographically random UUID
        raw = secrets.token_hex(16)
        new_id = f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:]}"
        try:
            self._store.set(_DEVICE_KEY, new_id)
        except Exception:
            pass
        return new_id

    # ── Internal ──────────────────────────────────────────────────────────────

    def _wipe_cache(self) -> None:
        for attr in ("_cached_cookie", "_cached_token"):
            val = getattr(self, attr, None)
            if val:
                setattr(self, attr, secrets.token_hex(max(len(val) // 2, 1)))
                setattr(self, attr, None)
        self._cached_jar = None

    def __del__(self) -> None:
        self._wipe_cache()


# Module-level singleton
_credential_store: Optional[CredentialStore] = None


def get_credential_store() -> CredentialStore:
    """Return the shared CredentialStore instance."""
    global _credential_store
    if _credential_store is None:
        _credential_store = CredentialStore()
    return _credential_store
