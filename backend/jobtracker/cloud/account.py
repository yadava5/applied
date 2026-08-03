"""Account deletion — purge all of the caller's data.

The web "danger zone" (``apps/web/app/api/account/delete/route.ts``) calls
``DELETE {BACKEND_API_URL}/account`` with the user's bearer token *before* it
removes the Supabase auth user, so a user's Postgres rows are purged rather
than left orphaned. This router provides that previously-missing endpoint.

Every entity table carries ``user_id`` and the request runs under the per-user
RLS context (the ``jobtracker_app`` role + the ``request.jwt.claims`` GUC set
from ``set_current_user_id``), so each delete is doubly scoped to the caller:
an explicit ``WHERE user_id = <caller>`` filter AND row-level security. Rows are
removed children-before-parents to respect the (RESTRICT-default) foreign keys:
``email_embeddings → emails`` and ``contacts / interviews / emails →
applications``. ``training_data``, ``sync_state`` and ``user_credentials`` carry
no cross-entity FK.
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

# Children before parents (see module docstring). Order matters because the
# foreign keys default to RESTRICT — deleting a parent first would error.
_DELETION_ORDER: tuple[type, ...] = (
    EmailEmbedding,
    Contact,
    Interview,
    Email,
    Application,
    TrainingData,
    SyncState,
    UserCredential,
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
    gone and the web flow can retry. (Google-side token revocation is a
    follow-up; deleting ``user_credentials`` here removes our stored copy.)
    """

    # ``get_session()`` is the async context manager used across the cloud
    # handlers; its transaction ``begin`` sets the RLS ``request.jwt.claims``
    # GUC from the per-request user-id ContextVar (populated by require_user).
    async with get_session() as session:
        for model in _DELETION_ORDER:
            await session.exec(sa_delete(model).where(model.user_id == user_id))
        await session.commit()

    logger.info(
        "account.deleted user_id=%s tables_cleared=%d",
        user_id,
        len(_DELETION_ORDER),
    )
    return AccountDeletionResponse(deleted=True, tables_cleared=len(_DELETION_ORDER))
