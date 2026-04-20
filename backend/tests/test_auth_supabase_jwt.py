"""Unit tests for ``jobtracker.auth.supabase_jwt`` (issue #20, C3).

The ``current_user`` dependency is the single integration point between
the HTTP boundary and the cloud backend; everything else assumes it
returns a valid UUID. These tests exercise every branch:

- Valid HS256 token with proper ``sub``/``aud``/``exp`` → UUID.
- Missing ``Authorization`` header → 401.
- Missing ``Bearer `` prefix → 401.
- Expired JWT → 401.
- Wrong signing secret (signature mismatch) → 401.
- Wrong audience (not ``"authenticated"``) → 401.
- ``sub`` claim absent or not a UUID → 401.
- Algorithm confusion (``alg: none``) → 401.
- ``settings.supabase_jwt_secret`` not configured → 401.

We call the dependency coroutine directly (no FastAPI app) so the tests
stay fast and don't need an HTTP client. Test coverage of the
end-to-end wire-up (``/auth/me`` returning the decoded user) lives in
``test_user_id_scoping.py``.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import jwt as pyjwt
import pytest

from jobtracker.auth.supabase_jwt import AuthError, current_user


# 32+ bytes of entropy to satisfy PyJWT's HMAC length warning; values
# are irrelevant as long as they are consistent within the test module.
JWT_SECRET = "super-secret-test-key-do-not-use-in-prod-32+-bytes"
JWT_WRONG_SECRET = "another-secret-that-does-not-match-and-is-also-long-enough"


def _make_token(
    *,
    sub: str | None = "11111111-1111-1111-1111-111111111111",
    aud: str | Any = "authenticated",
    exp: int | None = None,
    secret: str = JWT_SECRET,
    algorithm: str = "HS256",
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Build a Supabase-flavoured JWT for testing.

    ``exp`` defaults to "5 minutes from now". Pass ``exp=<past>`` to
    exercise the expiry branch. Set individual claims to ``None`` to
    omit them (tests the missing-claim branches).
    """

    now = int(time.time())
    payload: dict[str, Any] = {"iat": now}
    if sub is not None:
        payload["sub"] = sub
    if aud is not None:
        payload["aud"] = aud
    payload["exp"] = exp if exp is not None else now + 300
    if extra_claims:
        payload.update(extra_claims)

    return pyjwt.encode(payload, secret, algorithm=algorithm)


@pytest.fixture
def configured_secret(monkeypatch: pytest.MonkeyPatch):
    """Patch ``settings.supabase_jwt_secret`` for the duration of a test."""

    import jobtracker.config as config_module

    monkeypatch.setattr(config_module.settings, "supabase_jwt_secret", JWT_SECRET)
    # ``supabase_jwt`` imports ``settings`` by reference, so patching the
    # attribute on the singleton is enough — no reload required.
    yield JWT_SECRET


async def test_valid_token_returns_uuid(configured_secret: str) -> None:
    sub = "22222222-2222-2222-2222-222222222222"
    token = _make_token(sub=sub)

    result = await current_user(authorization=f"Bearer {token}")

    assert isinstance(result, uuid.UUID)
    assert str(result) == sub


async def test_missing_header_raises_401(configured_secret: str) -> None:
    with pytest.raises(AuthError) as excinfo:
        await current_user(authorization=None)

    assert excinfo.value.status_code == 401
    assert "Missing Authorization" in excinfo.value.detail


async def test_non_bearer_scheme_raises_401(configured_secret: str) -> None:
    token = _make_token()
    with pytest.raises(AuthError) as excinfo:
        await current_user(authorization=f"Basic {token}")

    assert excinfo.value.status_code == 401
    assert "Bearer" in excinfo.value.detail


async def test_empty_bearer_token_raises_401(configured_secret: str) -> None:
    with pytest.raises(AuthError):
        await current_user(authorization="Bearer ")


async def test_expired_token_raises_401(configured_secret: str) -> None:
    # 10 minutes in the past.
    token = _make_token(exp=int(time.time()) - 600)

    with pytest.raises(AuthError) as excinfo:
        await current_user(authorization=f"Bearer {token}")

    assert excinfo.value.status_code == 401
    assert "expired" in excinfo.value.detail.lower()


async def test_wrong_signature_raises_401(configured_secret: str) -> None:
    token = _make_token(secret=JWT_WRONG_SECRET)

    with pytest.raises(AuthError) as excinfo:
        await current_user(authorization=f"Bearer {token}")

    assert excinfo.value.status_code == 401
    # The error message is generic ("Invalid signature" OR "Invalid token"
    # depending on PyJWT's failure path — verifying the signature is
    # rejected is the contract, not the exact string).
    assert "invalid" in excinfo.value.detail.lower() or "signature" in excinfo.value.detail.lower()


async def test_wrong_audience_raises_401(configured_secret: str) -> None:
    token = _make_token(aud="service_role")

    with pytest.raises(AuthError) as excinfo:
        await current_user(authorization=f"Bearer {token}")

    assert excinfo.value.status_code == 401
    assert "audience" in excinfo.value.detail.lower()


async def test_missing_sub_raises_401(configured_secret: str) -> None:
    token = _make_token(sub=None)

    with pytest.raises(AuthError) as excinfo:
        await current_user(authorization=f"Bearer {token}")

    assert excinfo.value.status_code == 401
    # ``require=[...]`` triggers MissingRequiredClaimError → "Missing claim".
    assert "missing" in excinfo.value.detail.lower() or "subject" in excinfo.value.detail.lower()


async def test_non_uuid_sub_raises_401(configured_secret: str) -> None:
    token = _make_token(sub="not-a-uuid")

    with pytest.raises(AuthError) as excinfo:
        await current_user(authorization=f"Bearer {token}")

    assert excinfo.value.status_code == 401
    assert "subject" in excinfo.value.detail.lower()


async def test_alg_none_rejected(configured_secret: str) -> None:
    """An ``alg: none`` token must not be accepted regardless of content.

    This is the classic JWT library confusion vulnerability. PyJWT
    rejects ``alg: none`` by default when an algorithm list is passed
    to ``decode``; we assert the behaviour here so any future
    refactor that silently re-enables it trips this test.
    """

    payload = {
        "sub": "33333333-3333-3333-3333-333333333333",
        "aud": "authenticated",
        "exp": int(time.time()) + 300,
        "iat": int(time.time()),
    }
    # Encoding with alg=none produces a signature-less token.
    token = pyjwt.encode(payload, key="", algorithm="none")

    with pytest.raises(AuthError):
        await current_user(authorization=f"Bearer {token}")


async def test_missing_secret_raises_401(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the deployment forgot to set ``SUPABASE_JWT_SECRET``, every
    request is rejected — we cannot validate tokens without a key."""

    import jobtracker.config as config_module

    monkeypatch.setattr(config_module.settings, "supabase_jwt_secret", None)

    token = _make_token()
    with pytest.raises(AuthError) as excinfo:
        await current_user(authorization=f"Bearer {token}")

    assert excinfo.value.status_code == 401
    assert "not configured" in excinfo.value.detail.lower()


async def test_wrong_algorithm_rs256_rejected(configured_secret: str) -> None:
    """Tokens claiming ``alg: RS256`` cannot be validated with our HS256
    secret; PyJWT's ``algorithms=["HS256"]`` filter must reject them.

    We can't easily construct a valid RS256 token without a keypair, so
    we hand-craft a token with an RS256 header and any body — PyJWT
    should refuse to even attempt verification.
    """

    import base64
    import json

    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "RS256", "typ": "JWT"}).encode()
    ).rstrip(b"=").decode()
    body = base64.urlsafe_b64encode(
        json.dumps(
            {
                "sub": "44444444-4444-4444-4444-444444444444",
                "aud": "authenticated",
                "exp": int(time.time()) + 300,
            }
        ).encode()
    ).rstrip(b"=").decode()
    bogus_token = f"{header}.{body}.deadbeef"

    with pytest.raises(AuthError):
        await current_user(authorization=f"Bearer {bogus_token}")
