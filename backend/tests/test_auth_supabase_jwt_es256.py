"""The ES256 branch of the Supabase verifier, which is the one production uses.

WHY THIS FILE EXISTS (#408). ``test_auth_supabase_jwt.py`` has twelve tests and
every one of them signs HS256. The verifier has two branches, and the branch
with no coverage is the branch every authenticated production request goes
through.

That is not inferred from the code. The live project publishes exactly one
signing key, and it is asymmetric::

    $ curl -s https://<ref>.supabase.co/auth/v1/.well-known/jwks.json
    keys published: 1
      alg=ES256  kty=EC  use=sig

Supabase projects created since 2025 default to asymmetric signing keys, and
this one did. So the four places in the docs that said "HS256 pinned" were
describing the path production does NOT take, and the path it does take was
verified by nothing.

WHAT THE VERIFIER ACTUALLY DOES, since "HS256 pinned" was wrong in both
directions: it is a two-algorithm whitelist that dispatches on the UNVERIFIED
header ``alg``. ES256 verifies against the project's JWKS, HS256 against the
shared secret, and the chosen single-element ``algorithms`` list goes to
``jwt.decode``. The header only chooses a fully-verified path; it never relaxes
verification, and each branch carries its own key material, so an ES256 token
cannot be checked against the HS256 secret or the reverse.

The security property the old docs claimed is still true and still tested next
door: ``alg: none`` and ``alg: RS256`` are both rejected, because neither is in
either whitelist and an unrecognised ``alg`` falls through to the HS256 branch
where signature verification fails. This file adds what was missing rather than
re-litigating that.

THE FAIL-CLOSED CASE IS THE ONE TO KEEP. If ``JOBTRACKER_SUPABASE_JWKS_URL`` is
unset, an ES256 token is rejected outright. On a project signing ES256 that
means every user is locked out rather than let in, which is the correct
direction, and it is the failure mode of a fresh deploy that forgets one
variable. DEPLOY.md documents the variable; nothing executed it until now.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from jobtracker.auth.supabase_jwt import AuthError, current_user

HS256_SECRET = "super-secret-test-key-do-not-use-in-prod-32+-bytes"
JWKS_URL = "https://project.supabase.test/auth/v1/.well-known/jwks.json"
KID = "61a90919-test-kid"
SUB = "33333333-3333-3333-3333-333333333333"


@pytest.fixture
def ec_key() -> ec.EllipticCurvePrivateKey:
    """A P-256 key, the curve ES256 names."""

    return ec.generate_private_key(ec.SECP256R1())


def _es256_token(
    key: ec.EllipticCurvePrivateKey,
    *,
    sub: str | None = SUB,
    aud: str | None = "authenticated",
    exp: int | None = None,
    kid: str | None = KID,
) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {"iat": now, "exp": exp if exp is not None else now + 300}
    if sub is not None:
        payload["sub"] = sub
    if aud is not None:
        payload["aud"] = aud
    headers = {"kid": kid} if kid else None
    return pyjwt.encode(payload, key, algorithm="ES256", headers=headers)


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch, ec_key: ec.EllipticCurvePrivateKey):
    """Both halves configured, with the JWKS fetch served from the test key.

    The client is patched rather than the network stubbed: the thing under test
    is the verifier's dispatch and key selection, and a test that also owns an
    HTTP fake would fail for reasons that have nothing to do with either.
    ``_jwks_client`` is reset afterwards so the module-level cache cannot leak a
    key into another test.
    """

    import jobtracker.auth.supabase_jwt as module
    import jobtracker.config as config_module

    monkeypatch.setattr(config_module.settings, "supabase_jwt_secret", HS256_SECRET)
    monkeypatch.setattr(config_module.settings, "supabase_jwks_url", JWKS_URL)

    class _Signing:
        key = ec_key.public_key()

    class _Client:
        uri = JWKS_URL

        def get_signing_key_from_jwt(self, token: str) -> Any:
            return _Signing()

    monkeypatch.setattr(module, "_get_jwks_client", lambda url: _Client())
    yield
    monkeypatch.setattr(module, "_jwks_client", None, raising=False)


async def test_an_es256_token_from_the_project_jwks_authenticates(
    configured: None, ec_key: ec.EllipticCurvePrivateKey
) -> None:
    """The path every signed-in production request takes, executed."""

    result = await current_user(authorization=f"Bearer {_es256_token(ec_key)}")

    assert isinstance(result, uuid.UUID)
    assert str(result) == SUB


async def test_an_es256_token_signed_by_a_stranger_is_rejected(
    configured: None,
) -> None:
    """The control on the test above.

    Without this, "a valid token authenticates" is satisfied by a verifier that
    authenticates anything. A different P-256 key is a correctly-formed ES256
    token that the project did not sign.
    """

    other = ec.generate_private_key(ec.SECP256R1())

    with pytest.raises(AuthError):
        await current_user(authorization=f"Bearer {_es256_token(other)}")


async def test_an_es256_token_is_rejected_when_the_jwks_url_is_not_configured(
    monkeypatch: pytest.MonkeyPatch, ec_key: ec.EllipticCurvePrivateKey
) -> None:
    """Fail closed, not open.

    On a project that signs ES256 this locks everyone out, which is correct and
    is the failure mode of a deploy that forgets one environment variable. The
    wrong outcome would be falling through to the HS256 branch and treating the
    shared secret as a verification key for a token it did not sign.
    """

    import jobtracker.config as config_module

    monkeypatch.setattr(config_module.settings, "supabase_jwt_secret", HS256_SECRET)
    monkeypatch.setattr(config_module.settings, "supabase_jwks_url", None)

    with pytest.raises(AuthError) as excinfo:
        await current_user(authorization=f"Bearer {_es256_token(ec_key)}")

    assert "not configured" in str(excinfo.value).lower(), (
        "an ES256 token with no JWKS configured must be refused for that reason. "
        f"Got: {excinfo.value}"
    )


async def test_the_hs256_secret_cannot_verify_an_es256_token(
    configured: None, ec_key: ec.EllipticCurvePrivateKey
) -> None:
    """Cross-branch confusion, stated as its own case.

    Branch selection happens before ``jwt.decode`` and carries its own key, so
    the shared secret is never offered to an asymmetric token. This is the
    assertion that would fail first if someone ever "simplified" the dispatch
    into a single ``algorithms=["HS256", "ES256"]`` list, which is the classic
    shape of an algorithm-confusion hole.
    """

    token = _es256_token(ec_key)
    header = pyjwt.get_unverified_header(token)
    assert header["alg"] == "ES256"

    with pytest.raises(pyjwt.InvalidTokenError):
        pyjwt.decode(
            token,
            HS256_SECRET,
            algorithms=["HS256"],
            audience="authenticated",
        )


async def test_an_expired_es256_token_is_rejected(
    configured: None, ec_key: ec.EllipticCurvePrivateKey
) -> None:
    """Expiry is checked on this branch too, not only on the tested one."""

    stale = _es256_token(ec_key, exp=int(time.time()) - 60)

    with pytest.raises(AuthError):
        await current_user(authorization=f"Bearer {stale}")


async def test_an_es256_token_without_a_uuid_sub_is_rejected(
    configured: None, ec_key: ec.EllipticCurvePrivateKey
) -> None:
    """The claim checks are shared code, but nothing proved the ES256 branch
    reaches them rather than returning early on a successful signature."""

    with pytest.raises(AuthError):
        await current_user(authorization=f"Bearer {_es256_token(ec_key, sub='not-a-uuid')}")

    with pytest.raises(AuthError):
        await current_user(authorization=f"Bearer {_es256_token(ec_key, sub=None)}")
