"""
Shared pytest fixtures and configuration for Suno MCP tests.
"""
import asyncio
import base64
import json
import time
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── JWT factory ───────────────────────────────────────────────────────────────

def make_jwt(
    exp_offset: int = 3600,
    user_id: str = "test-user-123",
    session_id: str = "session_test123",
    email: str = "test@example.com",
    iat_offset: int = 0,
) -> str:
    """Create a minimal Suno-format JWT for testing (unsigned)."""
    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "RS256", "kid": "test-key", "typ": "JWT"}).encode()
    ).decode().rstrip("=")

    now = int(time.time()) + iat_offset
    payload_data = {
        "suno.com/claims/user_id": user_id,
        "https://suno.ai/claims/clerk_id": f"user_{session_id}",
        "suno.com/claims/token_type": "access",
        "exp": now + exp_offset,
        "aud": "suno-api",
        "sub": f"user_{session_id}",
        "azp": "https://suno.com",
        "iat": now,
        "iss": "https://auth.suno.com",
        "jit": "test-jit-id",
        "viz": False,
        "sid": session_id,
        "suno.com/claims/email": email,
        "https://suno.ai/claims/email": email,
    }
    payload = base64.urlsafe_b64encode(
        json.dumps(payload_data).encode()
    ).decode().rstrip("=")
    return f"{header}.{payload}.fakesig"


def make_expired_jwt() -> str:
    return make_jwt(exp_offset=-10)  # expired 10 seconds ago


def make_fresh_jwt() -> str:
    return make_jwt(exp_offset=3600)  # expires in 1 hour


def make_expiring_soon_jwt() -> str:
    return make_jwt(exp_offset=60)  # expires in 60 seconds (within 5-min buffer)


# ── Standard cookie jars ──────────────────────────────────────────────────────

FRESH_JWT = make_fresh_jwt()
EXPIRED_JWT = make_expired_jwt()


def make_cookie_jar(jwt: str = None, include_client: bool = True) -> Dict[str, str]:
    """Build a representative suno.com cookie jar for testing."""
    jar = {
        "__session": jwt or FRESH_JWT,
        "__client_uat": str(int(time.time())),
        "suno_device_id": "test-device-uuid-1234",
        "has_logged_in_before": "true",
        "clerk_active_context": "session_test123:",
        "ssr_bucket": "42",
    }
    if include_client:
        jar["__client"] = "test_clerk_client_token_value"
    return jar


@pytest.fixture
def fresh_jwt():
    return make_fresh_jwt()


@pytest.fixture
def expired_jwt():
    return make_expired_jwt()


@pytest.fixture
def expiring_soon_jwt():
    return make_expiring_soon_jwt()


@pytest.fixture
def cookie_jar_with_client():
    return make_cookie_jar(include_client=True)


@pytest.fixture
def cookie_jar_without_client():
    return make_cookie_jar(include_client=False)


# ── Async event loop ──────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
