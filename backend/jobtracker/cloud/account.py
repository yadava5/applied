"""Account deletion — purge all of the caller's data.

The web "danger zone" (``apps/web/app/api/account/delete/route.ts``) calls
``DELETE {BACKEND_API_URL}/account`` with the user's bearer token *before* it
removes the Supabase auth user, so a user's Postgres rows are purged rather
than left orphaned. This router provides that previously-missing endpoint.

Every entity table carries ``user_id`` and the request runs under the per-user
RLS context (the ``jobtracker_app`` role + the ``request.jwt.claims`` GUC set
from ``set_current_user_id``), so each delete is doubly scoped to the caller:
an explicit ``WHERE user_id = <caller>`` filter AND row-level security. Rows are
removed children-before-parents — ``email_embeddings → emails`` and
``contacts / interviews / emails → applications``. ``training_data``,
``sync_state``, ``user_credentials`` and ``gmail_sync_enrollment`` carry no
cross-entity FK.

Those four keys are ``ON DELETE CASCADE`` since ``a9d3e5f2c841``; before it they
were NO ACTION and this ordering was mandatory rather than merely correct. It is
KEPT anyway, and not from inertia: the child deletes are scoped by ``user_id``
as well, which is a second layer the database's cascade does not provide, and
this repo has already found that DDL it assumed was applied can be absent in
production. Belt and braces — the cascade is what makes a purge interrupted
half-way stop leaving orphans that RLS then makes permanently unreachable.

Before any of that, the caller's Gmail grant is revoked at Google — the
``user_credentials`` row is the only place the token exists, so once the purge
runs there is nothing left to revoke. See ``delete_account`` for why that
revocation is best-effort and cannot block the deletion.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends
from fastapi import status as http_status
from pydantic import BaseModel
from sqlalchemy import delete as sa_delete

from jobtracker.auth import current_user, require_user
from jobtracker.database import get_session
from jobtracker.database.models import (
    Application,
    Contact,
    Email,
    EmailEmbedding,
    GmailSyncEnrollment,
    Interview,
    SyncState,
    TrainingData,
    UserCredential,
)

logger = logging.getLogger(__name__)

# Router-level ``require_user()`` mirrors the applications router: it verifies
# the JWT and sets the per-request user-id ContextVar that the DB layer turns
# into the RLS ``request.jwt.claims`` GUC. Without it, the deletes would run
# with no identity and RLS would fail closed (delete nothing).
router = APIRouter(tags=["Account"], dependencies=[require_user()])

# Children before parents (see module docstring). Kept explicit even though the
# four cross-entity keys now cascade: these deletes are also user-scoped, which
# the cascade is not.
_DELETION_ORDER: tuple[type, ...] = (
    EmailEmbedding,
    Contact,
    Interview,
    Email,
    Application,
    TrainingData,
    SyncState,
    UserCredential,
    # The membership fact published for the scheduled sync (issue #291). It
    # holds no secret, but it holds the user's id — leaving it behind would
    # mean a deleted account still appears in the cron's candidate set, and
    # ``test_account_deletion_covers_every_table`` derives this list from every
    # table carrying a ``user_id`` precisely so that cannot be forgotten.
    GmailSyncEnrollment,
)


class AccountDeletionResponse(BaseModel):
    """Result of purging the caller's data."""

    deleted: bool = True
    tables_cleared: int


@router.delete(
    "/account",
    response_model=AccountDeletionResponse,
    status_code=http_status.HTTP_200_OK,
    summary="Delete the authenticated user's data",
)
async def delete_account(
    user_id: uuid.UUID = Depends(current_user),
) -> AccountDeletionResponse:
    """Purge every row owned by the authenticated user.

    Idempotent — deleting an already-empty account still returns 200. The
    caller's Supabase *auth* user is removed separately by the web layer
    **after** this returns, so a failure here surfaces before the auth user is
    gone and the web flow can retry.

    Google-side token revocation is no longer a follow-up (issue #215): the
    grant is revoked at Google *before* ``user_credentials`` is deleted, since
    that row is the only place the token still exists.
    """

    # Revoke the Gmail grant first — after the row delete there is no token
    # left to revoke, so this is the only moment it can happen. Reuses the
    # disconnect path's revocation rather than a second implementation.
    #
    # Function-level import to keep the account router free of the OAuth
    # module's heavy Google imports at collection time, matching the way
    # ``gmail_disconnect`` reaches ``clear_gmail_sync_state``.
    #
    # Best-effort, deliberately: ``revoke_stored_gmail_grant`` never raises,
    # and a False answer does NOT abort the deletion. The two failures are not
    # symmetric — a grant left standing at Google is a real harm the user can
    # still fix themselves at myaccount.google.com/permissions, whereas
    # refusing to delete the account because Google was unreachable strands
    # them with the data they asked us to destroy. The stored token is removed
    # either way.
    #
    # The ``try`` is not distrust of that promise so much as coverage of what
    # the promise does not span: the import itself, and ``_revoke_at_google``
    # raising despite its own contract. Both would otherwise 500 the one
    # endpoint whose job is to let a user leave. It overlaps the helper's own
    # guard on the credential read, and that redundancy is deliberate — the
    # helper's guard keeps its contract for every caller, this one keeps this
    # handler's.
    try:
        from jobtracker.cloud.gmail_oauth import revoke_stored_gmail_grant

        revoked = await revoke_stored_gmail_grant(user_id)
    except Exception as exc:  # noqa: BLE001 — see above
        logger.warning(
            "Gmail revocation raised during account deletion for user_id=%s: %s",
            user_id,
            type(exc).__name__,
        )
        revoked = False

    # ``get_session()`` is the async context manager used across the cloud
    # handlers; its transaction ``begin`` sets the RLS ``request.jwt.claims``
    # GUC from the per-request user-id ContextVar (populated by require_user).
    async with get_session() as session:
        for model in _DELETION_ORDER:
            await session.exec(sa_delete(model).where(model.user_id == user_id))
        await session.commit()

    logger.info(
        "account.deleted user_id=%s tables_cleared=%d google_revoked=%s",
        user_id,
        len(_DELETION_ORDER),
        revoked,
    )
    return AccountDeletionResponse(deleted=True, tables_cleared=len(_DELETION_ORDER))
