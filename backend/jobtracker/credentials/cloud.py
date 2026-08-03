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
from jobtracker.database.models import UserCredential

logger = logging.getLogger(__name__)


KIND_GMAIL = "gmail_oauth"
KIND_ICLOUD = "icloud_mail"
ACTIVE_KEY_ID = "v1"


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


async def _fetch_credential(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    kind: str,
) -> Optional[UserCredential]:
    result = await session.exec(
        select(UserCredential).where(
            UserCredential.user_id == user_id,
            UserCredential.kind == kind,
        )
    )
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
    """Encrypt + persist Gmail OAuth credentials for ``user_id``."""

    fernet = _require_fernet()
    ciphertext = fernet.encrypt(credentials.to_json().encode("utf-8"))
    try:
        async with get_session() as session:
            await _upsert_credential(
                session, user_id=user_id, kind=KIND_GMAIL, ciphertext=ciphertext
            )
            await session.commit()
        logger.info("Gmail credentials saved for user_id=%s", user_id)
        return True
    except Exception as exc:  # noqa: BLE001 — DB + crypto errors
        logger.exception("Failed to save Gmail credentials: %s", exc)
        return False


async def get_gmail_credentials(user_id: uuid.UUID) -> Optional[GmailCredentials]:
    """Fetch + decrypt Gmail OAuth credentials for ``user_id``.

    Returns ``None`` on miss; logs-and-returns-``None`` on decrypt failure
    rather than raising so routers degrade gracefully.
    """

    fernet = _require_fernet()
    async with get_session() as session:
        row = await _fetch_credential(session, user_id=user_id, kind=KIND_GMAIL)
    if row is None:
        logger.debug("No Gmail credentials stored for user_id=%s", user_id)
        return None
    try:
        plaintext = fernet.decrypt(row.ciphertext).decode("utf-8")
    except InvalidToken as exc:
        logger.error(
            "Fernet decrypt failed for Gmail credentials user_id=%s: %s",
            user_id,
            exc,
        )
        return None
    return GmailCredentials.from_json(plaintext)


async def delete_gmail_credentials(user_id: uuid.UUID) -> bool:
    """Remove the stored Gmail credential row for ``user_id``."""

    async with get_session() as session:
        await session.exec(
            delete(UserCredential).where(
                UserCredential.user_id == user_id,
                UserCredential.kind == KIND_GMAIL,
            )
        )
        await session.commit()
    logger.info("Gmail credentials deleted for user_id=%s", user_id)
    return True


async def update_gmail_access_token(
    user_id: uuid.UUID, access_token: str, token_expiry: datetime
) -> bool:
    """Refresh the stored Gmail access_token/token_expiry for ``user_id``."""

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
        logger.info("iCloud credentials saved for user_id=%s", user_id)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to save iCloud credentials: %s", exc)
        return False


async def get_icloud_credentials(
    user_id: uuid.UUID,
) -> Optional[ICloudCredentials]:
    fernet = _require_fernet()
    async with get_session() as session:
        row = await _fetch_credential(session, user_id=user_id, kind=KIND_ICLOUD)
    if row is None:
        return None
    try:
        plaintext = fernet.decrypt(row.ciphertext).decode("utf-8")
    except InvalidToken as exc:
        logger.error(
            "Fernet decrypt failed for iCloud credentials user_id=%s: %s",
            user_id,
            exc,
        )
        return None
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
    return True


async def has_icloud_credentials(user_id: uuid.UUID) -> bool:
    return (await get_icloud_credentials(user_id)) is not None


# -----------------------------------------------------------------------------
# Bulk
# -----------------------------------------------------------------------------


async def clear_all_credentials(user_id: uuid.UUID) -> bool:
    """Remove every credential row owned by ``user_id``."""

    async with get_session() as session:
        await session.exec(
            delete(UserCredential).where(UserCredential.user_id == user_id)
        )
        await session.commit()
    logger.info("All cloud credentials cleared for user_id=%s", user_id)
    return True
