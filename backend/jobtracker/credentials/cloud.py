"""Cloud credential backend (issue #21, C4).

Stores Gmail OAuth tokens and iCloud app-specific passwords as
Fernet-encrypted rows in the ``user_credentials`` Postgres table
(see ``jobtracker.database.models.UserCredential``). Used by
cloud routers — Gmail web OAuth (C5), iCloud web form (C5), and
cron sync (C7) — never by desktop.

Public API is **async** and every function takes ``user_id: UUID``
as the first positional argument. This intentionally differs from
the desktop sync-and-single-user API exposed at
``jobtracker.credentials.desktop``; cloud callers must be explicit
about which user they are acting on behalf of.

Encryption
----------
- ``cryptography.fernet.Fernet`` with the key in
  ``settings.secret_encryption_key`` (urlsafe base64, 32 bytes).
  Generate one with::

      python -c "from cryptography.fernet import Fernet; \
                 print(Fernet.generate_key().decode())"

- Fernet embeds its own IV in the token, so the ``nonce`` column is
  stored as an empty byte string. The column is reserved for a
  future AEAD (e.g. ChaCha20-Poly1305) upgrade that requires a
  separate nonce.

- Key rotation is scaffolded via ``key_id`` but v1 ships single-key.
  Adding more keys later is additive: decrypt first tries the
  active key, then falls back through old keys; after a successful
  old-key decrypt, the row is re-encrypted with the active key.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel.ext.asyncio.session import AsyncSession

from jobtracker.config import settings
from jobtracker.credentials.types import GmailCredentials, ICloudCredentials
from jobtracker.database import get_session
from jobtracker.database.models import GmailSyncEnrollment, UserCredential

logger = logging.getLogger(__name__)


KIND_GMAIL = "gmail_oauth"
KIND_ICLOUD = "icloud_mail"
ACTIVE_KEY_ID = "v1"


# -----------------------------------------------------------------------------
# Secret access log (CASA AL1, control 6.7.1 — "access to secrets is logged")
# -----------------------------------------------------------------------------
#
# One line shape for every touch of a stored credential, so an assessor reads a
# single format rather than eight ad-hoc sentences. The fields are the whole
# record an audit asks for: WHO (user_id), WHICH SECRET (kind), WHICH KEY
# VERSION (key_id), WHAT WAS DONE (op) and WHAT HAPPENED (outcome).
#
# What is deliberately NOT here is the point of the control. The line carries no
# ciphertext, no plaintext and no key material, and it cannot: the arguments are
# an id, two short enum-ish strings and a key *name*. ``row.ciphertext``, the
# decrypted ``plaintext`` and ``settings.secret_encryption_key`` are never passed
# to a logging call in this module. `tests/test_secret_access_logging.py` holds
# that line — it drives a real save/read/delete round trip and asserts none of
# the three appears in any emitted record.
#
# ``op`` is one of: read, write, delete, clear.
# ``outcome`` is one of: hit, miss, decrypt_failed, written, write_failed,
# deleted.
_ACCESS_LOG_FORMAT = "secret_access user_id=%s kind=%s key_id=%s op=%s outcome=%s"


def _log_secret_access(
    *,
    user_id: uuid.UUID,
    kind: str,
    key_id: Optional[str],
    op: str,
    outcome: str,
) -> None:
    """Record one access attempt against a stored secret.

    ``key_id`` is ``None`` on the delete/clear paths on purpose: those issue a
    DELETE and never read a row, so there is no key version to name and adding
    a SELECT purely to fill this field would buy a round trip (~216 ms under the
    cloud engine's NullPool, issue #203) for a log field. ``None`` is the honest
    value — do not "fix" it with a lookup.
    """

    logger.info(_ACCESS_LOG_FORMAT, user_id, kind, key_id, op, outcome)


class CredentialEncryptionError(RuntimeError):
    """Raised when encryption/decryption fails or the key is missing."""


def _require_fernet() -> Fernet:
    """Build a Fernet instance from ``settings.secret_encryption_key``.

    Raises ``CredentialEncryptionError`` if the key is not configured
    or not a valid Fernet key. Callers (save/get helpers) catch the
    error and surface it as a startup-time configuration issue rather
    than a per-request failure.
    """

    key = settings.secret_encryption_key
    if not key:
        raise CredentialEncryptionError(
            "secret_encryption_key is not configured; cloud credential "
            "storage is unavailable until JOBTRACKER_SECRET_ENCRYPTION_KEY "
            "is set."
        )
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except (ValueError, TypeError) as exc:
        raise CredentialEncryptionError(
            f"secret_encryption_key is not a valid Fernet key: {exc}"
        ) from exc


async def _upsert_credential(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    kind: str,
    ciphertext: bytes,
) -> None:
    """Insert-or-update the (user_id, kind) credential row.

    Uses Postgres ``ON CONFLICT`` when available; falls back to a
    SELECT-then-UPDATE-or-INSERT flow on SQLite (used by tests).
    """

    now = datetime.utcnow()

    dialect = session.bind.dialect.name if session.bind else ""
    if dialect == "postgresql":
        stmt = pg_insert(UserCredential).values(
            user_id=user_id,
            kind=kind,
            ciphertext=ciphertext,
            nonce=b"",
            key_id=ACTIVE_KEY_ID,
            created_at=now,
            updated_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id", "kind"],
            set_={
                "ciphertext": stmt.excluded.ciphertext,
                "nonce": stmt.excluded.nonce,
                "key_id": stmt.excluded.key_id,
                "updated_at": stmt.excluded.updated_at,
                # RECONNECTING UN-REVOKES. Writing a fresh credential is the
                # only evidence that could exist that the grant is good again,
                # and without clearing this a user who reconnected would stay
                # invisible to the scheduled sync permanently — a wedge with no
                # self-service way out.
                "revoked_at": None,
            },
        )
        await session.exec(stmt)
        return

    # SQLite / tests: emulate the upsert with SELECT + UPDATE/INSERT.
    existing = (
        await session.exec(
            select(UserCredential).where(
                UserCredential.user_id == user_id,
                UserCredential.kind == kind,
            )
        )
    ).first()
    if existing is not None:
        # SQLModel select returns a Row when projecting the whole model
        # under asyncio; normalize to the model instance.
        row = existing[0] if hasattr(existing, "__getitem__") else existing
        row.ciphertext = ciphertext
        row.nonce = b""
        row.key_id = ACTIVE_KEY_ID
        row.updated_at = now
        row.revoked_at = None  # see the ON CONFLICT branch above
        session.add(row)
        return

    session.add(
        UserCredential(
            user_id=user_id,
            kind=kind,
            ciphertext=ciphertext,
            nonce=b"",
            key_id=ACTIVE_KEY_ID,
            created_at=now,
            updated_at=now,
        )
    )


async def _enroll_gmail(session: AsyncSession, *, user_id: uuid.UUID) -> None:
    """Publish "this user has a Gmail credential" to ``gmail_sync_enrollment``.

    Called from ``save_gmail_credentials`` on the caller's OWN session, so the
    row lands in the same transaction as the ciphertext (issue #291). Two
    statements, one commit: the tables cannot disagree about who is enrolled,
    because there is no moment at which one is written and the other is not.

    Idempotent, and deliberately does NOT refresh ``enrolled_at``. Every access
    token refresh goes through ``update_gmail_access_token`` -> this function,
    and a column that moved on each refresh would record "last refreshed"
    while being named "enrolled_at".
    """

    dialect = session.bind.dialect.name if session.bind else ""
    if dialect == "postgresql":
        stmt = pg_insert(GmailSyncEnrollment).values(user_id=user_id)
        await session.exec(stmt.on_conflict_do_nothing(index_elements=["user_id"]))
        return

    # SQLite / tests: emulate the upsert.
    existing = (
        await session.exec(
            select(GmailSyncEnrollment).where(GmailSyncEnrollment.user_id == user_id)
        )
    ).first()
    if existing is not None:
        return
    session.add(GmailSyncEnrollment(user_id=user_id))


async def _unenroll_gmail(session: AsyncSession, *, user_id: uuid.UUID) -> None:
    """Withdraw the enrollment fact, in the caller's transaction.

    The mirror of :func:`_enroll_gmail`: a user whose Gmail credential row is
    gone is not enrolled, and both facts are removed together or neither is.
    """

    await session.exec(
        delete(GmailSyncEnrollment).where(GmailSyncEnrollment.user_id == user_id)
    )


async def _fetch_credential(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    kind: str,
    include_revoked: bool = False,
) -> Optional[UserCredential]:
    """Fetch one credential row, EXCLUDING revoked grants by default.

    ``revoked_at`` is set by :func:`jobtracker.cloud.gmail_client` when Google
    rejects the refresh token — the grant is gone at the provider and no amount
    of retrying brings it back; only fresh consent does. This read used to
    ignore the column entirely, so a revoked row came back looking exactly like
    a live one. Everything downstream believed it: ``/auth/gmail/status``
    answered ``connected: true``, Settings told the user they were connected,
    and the cron — which DOES filter (``cloud/cron.py``) — quietly synced
    nothing for them. A user in that state had no way to find out and no
    affordance to fix it, because the UI only offers Disconnect to someone it
    believes is connected.

    ``include_revoked=True`` IS NOT A CONVENIENCE. Exactly two callers need it,
    and both are trying to CLEAN UP the grant rather than use it:

      - ``gmail_disconnect`` — a revoked row still holds ciphertext and still
        has an enrollment row occupying a connection-cap seat. Filtering it out
        of the disconnect path would strand both forever.
      - ``revoke_stored_gmail_grant`` (account deletion) — the mark is written
        from a string heuristic, so a LIVE grant can be mis-marked. Skipping
        revocation on the strength of that guess would leave a real grant
        standing at Google after the account is gone.

    Anything that wants to USE a credential must take the default. A caller
    that passes ``include_revoked=True`` and then makes an API call with what
    it gets back has reintroduced the bug.
    """

    conditions = [
        UserCredential.user_id == user_id,
        UserCredential.kind == kind,
    ]
    if not include_revoked:
        conditions.append(UserCredential.revoked_at.is_(None))  # type: ignore[union-attr]

    result = await session.exec(select(UserCredential).where(*conditions))
    row = result.first()
    if row is None:
        return None
    return row[0] if hasattr(row, "__getitem__") else row


# -----------------------------------------------------------------------------
# Gmail
# -----------------------------------------------------------------------------


async def save_gmail_credentials(
    user_id: uuid.UUID, credentials: GmailCredentials
) -> bool:
    """Encrypt + persist Gmail OAuth credentials for ``user_id``.

    Also publishes the enrollment fact to ``gmail_sync_enrollment`` **in the
    same transaction** (issue #291), so the scheduled sync can enumerate who
    has Gmail linked without any path to the tokens themselves. One commit
    covers both writes; a failure rolls both back.
    """

    fernet = _require_fernet()
    ciphertext = fernet.encrypt(credentials.to_json().encode("utf-8"))
    try:
        async with get_session() as session:
            await _upsert_credential(
                session, user_id=user_id, kind=KIND_GMAIL, ciphertext=ciphertext
            )
            await _enroll_gmail(session, user_id=user_id)
            await session.commit()
        _log_secret_access(
            user_id=user_id,
            kind=KIND_GMAIL,
            key_id=ACTIVE_KEY_ID,
            op="write",
            outcome="written",
        )
        return True
    except Exception as exc:  # noqa: BLE001 — DB + crypto errors
        _log_secret_access(
            user_id=user_id,
            kind=KIND_GMAIL,
            key_id=ACTIVE_KEY_ID,
            op="write",
            outcome="write_failed",
        )
        logger.exception("Failed to save Gmail credentials: %s", exc)
        return False


async def get_gmail_credentials(
    user_id: uuid.UUID,
    session: AsyncSession | None = None,
    *,
    include_revoked: bool = False,
) -> Optional[GmailCredentials]:
    """Fetch + decrypt Gmail OAuth credentials for ``user_id``.

    Returns ``None`` on miss; logs-and-returns-``None`` on decrypt failure
    rather than raising so routers degrade gracefully.

    ``include_revoked`` — a grant Google has already rejected is NOT returned
    unless a caller asks for it by name. See :func:`_fetch_credential` for the
    two callers that legitimately do, and for why every other caller must not.
    The flag lives here as well as on the private helper because every
    sensitive call site goes through this public getter, not through that one.

    ``session`` — reuse the caller's open session instead of opening one.
    Under the cloud engine's NullPool a session is a fresh TCP+TLS+auth
    connection (~216 ms from iad1, issue #203), so a read handler that already
    holds a session must pass it in rather than pay a second connection for
    one indexed SELECT. Callers with no session in hand (OAuth callback, cron
    sync) omit it and get the previous behaviour.
    """

    fernet = _require_fernet()
    if session is not None:
        row = await _fetch_credential(
            session, user_id=user_id, kind=KIND_GMAIL, include_revoked=include_revoked
        )
    else:
        async with get_session() as own_session:
            row = await _fetch_credential(
                own_session,
                user_id=user_id,
                kind=KIND_GMAIL,
                include_revoked=include_revoked,
            )
    if row is None:
        _log_secret_access(
            user_id=user_id, kind=KIND_GMAIL, key_id=None, op="read", outcome="miss"
        )
        return None
    try:
        plaintext = fernet.decrypt(row.ciphertext).decode("utf-8")
    except InvalidToken:
        # Kept at ERROR (a failed decrypt of a live credential is an incident,
        # not a warning) and extended in place rather than duplicated, so the
        # failure carries the same five fields as every other access line.
        #
        # The exception object used to be interpolated here and no longer is.
        # `cryptography.fernet.InvalidToken` is `class InvalidToken(Exception):
        # pass` with no `__str__`, and every one of the twelve raise sites in
        # fernet.py is a bare `raise InvalidToken` with no arguments — so `%s`
        # rendered the empty string and the old line ended in a dangling ": ".
        # Nothing is lost by dropping it, and a log line about a secret should
        # not interpolate an object a future release could start attaching the
        # offending token to.
        logger.error(
            _ACCESS_LOG_FORMAT + " error=InvalidToken",
            user_id,
            KIND_GMAIL,
            row.key_id,
            "read",
            "decrypt_failed",
        )
        return None
    _log_secret_access(
        user_id=user_id,
        kind=KIND_GMAIL,
        key_id=row.key_id,
        op="read",
        outcome="hit",
    )
    return GmailCredentials.from_json(plaintext)


async def delete_gmail_credentials(user_id: uuid.UUID) -> bool:
    """Remove the stored Gmail credential row for ``user_id``.

    Withdraws the ``gmail_sync_enrollment`` row in the same transaction — see
    :func:`_unenroll_gmail`. A disconnected user must stop being a scheduled
    sync candidate at the same instant their token stops existing.
    """

    async with get_session() as session:
        await session.exec(
            delete(UserCredential).where(
                UserCredential.user_id == user_id,
                UserCredential.kind == KIND_GMAIL,
            )
        )
        await _unenroll_gmail(session, user_id=user_id)
        await session.commit()
    _log_secret_access(
        user_id=user_id, kind=KIND_GMAIL, key_id=None, op="delete", outcome="deleted"
    )
    return True


async def update_gmail_access_token(
    user_id: uuid.UUID, access_token: str, token_expiry: datetime
) -> bool:
    """Refresh the stored Gmail access_token/token_expiry for ``user_id``.

    THE DEFAULT READ IS LOAD-BEARING. This reads, mutates, and writes back
    through ``save_gmail_credentials``, whose upsert clears ``revoked_at`` —
    that clause exists so RECONNECTING un-revokes. Before the read was
    filtered, a refresh against a revoked row travelled the same path and
    un-revoked the grant with no fresh consent behind it, quietly restoring a
    dead credential to "connected". Filtered, the row is not found, this
    returns ``False``, and the only thing that can clear the mark is a real
    trip through Google's consent screen. Do not pass ``include_revoked``.
    """

    credentials = await get_gmail_credentials(user_id)
    if credentials is None:
        logger.error(
            "Cannot update access token: no Gmail credentials for user_id=%s",
            user_id,
        )
        return False
    credentials.access_token = access_token
    credentials.token_expiry = token_expiry
    return await save_gmail_credentials(user_id, credentials)


async def has_gmail_credentials(user_id: uuid.UUID) -> bool:
    return (await get_gmail_credentials(user_id)) is not None


# -----------------------------------------------------------------------------
# iCloud
# -----------------------------------------------------------------------------


async def save_icloud_credentials(
    user_id: uuid.UUID, credentials: ICloudCredentials
) -> bool:
    """Encrypt + persist iCloud credentials for ``user_id``."""

    fernet = _require_fernet()
    ciphertext = fernet.encrypt(credentials.to_json().encode("utf-8"))
    try:
        async with get_session() as session:
            await _upsert_credential(
                session, user_id=user_id, kind=KIND_ICLOUD, ciphertext=ciphertext
            )
            await session.commit()
        _log_secret_access(
            user_id=user_id,
            kind=KIND_ICLOUD,
            key_id=ACTIVE_KEY_ID,
            op="write",
            outcome="written",
        )
        return True
    except Exception as exc:  # noqa: BLE001
        _log_secret_access(
            user_id=user_id,
            kind=KIND_ICLOUD,
            key_id=ACTIVE_KEY_ID,
            op="write",
            outcome="write_failed",
        )
        logger.exception("Failed to save iCloud credentials: %s", exc)
        return False


async def get_icloud_credentials(
    user_id: uuid.UUID,
) -> Optional[ICloudCredentials]:
    fernet = _require_fernet()
    async with get_session() as session:
        row = await _fetch_credential(session, user_id=user_id, kind=KIND_ICLOUD)
    if row is None:
        _log_secret_access(
            user_id=user_id, kind=KIND_ICLOUD, key_id=None, op="read", outcome="miss"
        )
        return None
    try:
        plaintext = fernet.decrypt(row.ciphertext).decode("utf-8")
    except InvalidToken:
        # See the Gmail decrypt site for why `exc` is no longer interpolated.
        logger.error(
            _ACCESS_LOG_FORMAT + " error=InvalidToken",
            user_id,
            KIND_ICLOUD,
            row.key_id,
            "read",
            "decrypt_failed",
        )
        return None
    _log_secret_access(
        user_id=user_id,
        kind=KIND_ICLOUD,
        key_id=row.key_id,
        op="read",
        outcome="hit",
    )
    return ICloudCredentials.from_json(plaintext)


async def delete_icloud_credentials(user_id: uuid.UUID) -> bool:
    async with get_session() as session:
        await session.exec(
            delete(UserCredential).where(
                UserCredential.user_id == user_id,
                UserCredential.kind == KIND_ICLOUD,
            )
        )
        await session.commit()
    _log_secret_access(
        user_id=user_id, kind=KIND_ICLOUD, key_id=None, op="delete", outcome="deleted"
    )
    return True


async def has_icloud_credentials(user_id: uuid.UUID) -> bool:
    return (await get_icloud_credentials(user_id)) is not None


# -----------------------------------------------------------------------------
# Bulk
# -----------------------------------------------------------------------------


def log_credentials_purged(user_id: uuid.UUID) -> None:
    """Emit the ``op=clear`` access record for a wholesale credential purge.

    Public, and the only thing in this module that is public *purely* for a
    caller outside it. The account-deletion purge
    (``jobtracker/cloud/account.py``) destroys ``user_credentials`` with a bulk
    ``DELETE`` inside one transaction spanning nine models, so it cannot route
    through :func:`clear_all_credentials` — that function owns its own session
    and its own commit. See ``delete_account`` for why that transaction is
    load-bearing. Issue #757.

    What the purge must NOT do is compose the record itself. An assessor is
    told (``docs/casa/SECRET-ACCESS-POLICY.md`` §3.1) that every access record
    has one shape and arrives under one logger name; a second module writing
    its own ``secret_access`` line is how those two facts stop being true. So
    the wording, the field values and ``logger`` stay here and the caller only
    fires it.

    ``kind="all"`` because one DELETE removes every row the user owns — naming
    a single ``kind`` would be a narrower claim than what happened. ``key_id``
    is ``None`` for the reason given in :func:`_log_secret_access`.
    """

    _log_secret_access(
        user_id=user_id, kind="all", key_id=None, op="clear", outcome="deleted"
    )


async def clear_all_credentials(user_id: uuid.UUID) -> bool:
    """Remove every credential row owned by ``user_id``.

    Includes the ``gmail_sync_enrollment`` row: this clears the Gmail
    credential too, and an enrollment that outlived its credential is exactly
    the drift the same-transaction writes exist to prevent.

    **No production caller** at present (issue #757): account deletion, the one
    flow this shape was written for, purges every tenant table in a single
    transaction and clears the credential row there instead. Stated here rather
    than left to a grep, because three tests exercise this function and none of
    them can tell that nothing in a request path does.
    """

    async with get_session() as session:
        await session.exec(
            delete(UserCredential).where(UserCredential.user_id == user_id)
        )
        await _unenroll_gmail(session, user_id=user_id)
        await session.commit()
    log_credentials_purged(user_id)
    return True
