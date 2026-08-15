"""Supabase JWT verification for cloud FastAPI routers.

Supabase issues HS256-signed JWTs for every signed-in user. The JWT's
``sub`` claim is the user's UUID in the ``auth.users`` table; the
``aud`` claim is ``"authenticated"`` for signed-in sessions. Verifying
those two claims plus the signature and expiry is sufficient for
per-request identity — anything beyond that (RBAC, per-table ACLs) is
delegated to Row-Level Security policies defined in
``backend/alembic/versions/a8d4ec5fba26_enable_rls_policies_postgres_only.py``.

This module is **cloud-only** — which, since the desktop app and its
unmounted routers were deleted (issue #73), is the only path there is.
The wording is kept because ``jobtracker.config`` still carries a
``deployment`` setting and a ``desktop`` value is still constructible.

Usage
-----

In a cloud-mounted router:

.. code-block:: python

    from fastapi import APIRouter, Depends
    from jobtracker.auth import current_user

    router = APIRouter(prefix="/applications", dependencies=[Depends(current_user)])

    @router.get("/me")
    async def me(user_id = Depends(current_user)):
        return {"user_id": str(user_id)}

Or use the ``require_user`` alias to express the contract at the
module level:

.. code-block:: python

    from jobtracker.auth import require_user

    router = APIRouter(prefix="/applications", dependencies=[require_user()])

Failure modes (all → HTTP 401)
------------------------------

- Missing ``Authorization`` header.
- Header does not start with ``Bearer ``.
- JWT signature does not verify (``InvalidSignatureError``).
- JWT expired (``ExpiredSignatureError``).
- ``aud`` claim is missing or not ``"authenticated"``.
- ``sub`` claim is missing or is not a valid UUID.
- ``settings.supabase_jwt_secret`` is not configured — treated as a
  server-side 401 because we cannot validate *any* token without it.
  The deployment is misconfigured, not the client; a 500 would be more
  accurate but leaks server state, so we keep the generic 401 and log
  the misconfiguration for operators.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import jwt
from fastapi import Depends, Header, HTTPException, status

from jobtracker.config import settings

logger = logging.getLogger(__name__)


# Supabase's default audience for signed-in user sessions. Other Supabase
# audiences (``"anon"``, ``"service_role"``) are keyed off the same JWT
# secret but carry broader permissions; we only accept signed-in users
# here. Anonymous / service calls bypass ``current_user`` by not
# sending an Authorization header and hitting routes that don't require
# auth (only the cloud ``/health`` + ``/`` today).
_SUPABASE_AUDIENCE = "authenticated"

# Supabase historically signed user tokens with HS256 (shared secret);
# projects created since 2025 default to asymmetric ES256 signing keys
# published at ``/auth/v1/.well-known/jwks.json``. We accept exactly
# these two, dispatching on the token header to the matching verified
# path — a spoofed ``alg: none`` (or anything else) is rejected before
# any verification is attempted.
_SUPABASE_ALGORITHMS: list[str] = ["HS256"]
_SUPABASE_ASYMMETRIC_ALGORITHMS: list[str] = ["ES256"]

# Cached JWKS client (keys are cached by PyJWKClient; a rotated key is
# refetched automatically on kid miss).
_jwks_client: jwt.PyJWKClient | None = None


def _get_jwks_client(jwks_url: str) -> jwt.PyJWKClient:
    global _jwks_client
    if _jwks_client is None or _jwks_client.uri != jwks_url:
        _jwks_client = jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=3600)
    return _jwks_client


class AuthError(HTTPException):
    """Raised by ``current_user`` on any auth failure.

    Subclassing ``HTTPException`` keeps FastAPI's error-response
    machinery fully engaged; ``detail`` is always a short opaque string
    (never the inner ``jwt`` exception message) so attackers cannot
    fingerprint the validator via its error codes.
    """

    def __init__(self, detail: str = "Not authenticated") -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )


def _decode_token(token: str, secret: str) -> dict[str, Any]:
    """Decode + verify the JWT. Raises :class:`AuthError` on any failure.

    Dispatches on the (unverified) header ``alg`` strictly: ES256 tokens
    verify against the project's JWKS (when configured), HS256 tokens
    against the shared secret. The header is only used to *choose* a
    fully-verified path, never to relax verification.
    """

    try:
        header_alg = jwt.get_unverified_header(token).get("alg")
    except jwt.InvalidTokenError:
        raise AuthError("Invalid token") from None

    key: Any = secret
    algorithms = _SUPABASE_ALGORITHMS
    if header_alg in _SUPABASE_ASYMMETRIC_ALGORITHMS:
        jwks_url = settings.supabase_jwks_url
        if not jwks_url:
            logger.error(
                "Received an ES256 Supabase token but JOBTRACKER_SUPABASE_JWKS_URL "
                "is not configured; rejecting."
            )
            raise AuthError("Auth not configured")
        try:
            key = _get_jwks_client(jwks_url).get_signing_key_from_jwt(token).key
        except jwt.PyJWKClientError:
            raise AuthError("Invalid signature") from None
        algorithms = _SUPABASE_ASYMMETRIC_ALGORITHMS

    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            key,
            algorithms=algorithms,
            audience=_SUPABASE_AUDIENCE,
            # ``pyjwt`` verifies ``exp``, ``iat``, ``nbf``, and signature
            # by default; we also want strict audience verification, which
            # is what ``audience=`` implies.
            options={
                "require": ["exp", "sub", "aud"],
            },
        )
    except jwt.ExpiredSignatureError:
        raise AuthError("Token expired") from None
    except jwt.InvalidAudienceError:
        raise AuthError("Invalid audience") from None
    except jwt.InvalidSignatureError:
        raise AuthError("Invalid signature") from None
    except jwt.MissingRequiredClaimError as exc:
        raise AuthError(f"Missing claim: {exc.claim}") from None
    except jwt.InvalidTokenError:
        # Catch-all for any other PyJWT error (bad format, bad alg, etc).
        # We deliberately do not leak the inner message.
        raise AuthError("Invalid token") from None

    return payload


def _extract_bearer(authorization: str | None) -> str:
    """Pull the bearer token out of an ``Authorization`` header."""

    if not authorization:
        raise AuthError("Missing Authorization header")

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise AuthError("Expected 'Authorization: Bearer <token>'")

    return token.strip()


async def current_user(
    authorization: str | None = Header(default=None),
) -> uuid.UUID:
    """FastAPI dependency: resolve the current Supabase user UUID.

    Returns the ``sub`` claim parsed into a :class:`uuid.UUID`. Raises
    :class:`AuthError` (HTTP 401) for any validation failure.

    This is the single integration point between the HTTP boundary and
    the rest of the cloud backend. Routers should depend on
    ``current_user`` (or the ``require_user`` alias below) rather than
    reaching into the headers directly.
    """

    secret = settings.supabase_jwt_secret
    if not secret:
        # Deployment-level misconfiguration. We treat this as "not
        # authenticated" rather than "server error" because the client's
        # recourse is identical (do not retry without new credentials).
        logger.error(
            "Supabase JWT secret not configured; cloud auth is rejecting all "
            "requests. Set JOBTRACKER_SUPABASE_JWT_SECRET."
        )
        raise AuthError("Auth not configured")

    token = _extract_bearer(authorization)
    payload = _decode_token(token, secret)

    sub = payload.get("sub")
    if not isinstance(sub, str):
        raise AuthError("Invalid subject")

    try:
        user_id = uuid.UUID(sub)
    except (ValueError, TypeError):
        raise AuthError("Invalid subject") from None

    # Bind this user as the RLS identity for the current request context so the
    # central engine wiring (jobtracker.database.connection) sets
    # ``request.jwt.claims`` on every transaction that runs the user's queries.
    # Imported lazily so this cloud-only module keeps its thin import graph.
    from jobtracker.database.connection import set_current_user_id

    set_current_user_id(user_id)
    return user_id


def require_user() -> Any:
    """Router-level convenience: ``Depends(current_user)``.

    Use this in ``APIRouter(dependencies=[require_user()])`` to apply
    the JWT check to every endpoint on the router. Individual handlers
    can still re-declare ``user: uuid.UUID = Depends(current_user)`` if
    they need the concrete UUID value inside the function body.
    """

    return Depends(current_user)
