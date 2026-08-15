"""a sync lease, and a revoked-credential marker

Revision ID: f4c2a8e17b95
Revises: e7a1c4d92b30
Create Date: 2026-08-14 13:00:00.000000

Two nullable timestamps, for two different "nothing stops this" defects.

``sync_state.sync_started_at`` — the per-user sync lease
--------------------------------------------------------

Nothing prevented one authenticated account from firing unlimited parallel
``POST /gmail/sync``. Each one is a scan of up to 750 messages, so the cost of
holding the button down is Vercel function-seconds, the user's own Gmail API
quota, and — worse than either — N copies of the additive merge racing each
other over the same rows.

``SyncState`` already carried a cursor and a ``status``, but no lease: nothing
recorded that a sync was *in flight*, only that one had finished. This column
is that record. It holds the instant the current sync started, and NULL when
none is running.

WHY A TIMESTAMP AND NOT A BOOLEAN. A crashed sync must not wedge the user out
of their own mailbox forever, and a boolean flag has no way to expire — a
function killed mid-scan (Vercel's 60 s ceiling, an OOM, a deploy) would leave
it set with nobody left to clear it. A timestamp lets the lease be read as
"held only if it started within the TTL", so the worst a crash costs is one TTL
of waiting rather than a permanent lockout. See ``_SYNC_LEASE_TTL_SECONDS`` in
``cloud/sync_state.py``, sized above the 60 s function ceiling.

``user_credentials.revoked_at`` — the grant the user took back
---------------------------------------------------------------

When a user revokes Gmail access at myaccount.google.com, the refresh fails and
``load_valid_credentials`` correctly degrades to "reconnect required". But
nothing was ever written down. The credential row stayed, so
``cron._gmail_sync_position`` kept answering ``has_gmail=True`` and that user
kept occupying one of the ~4 candidate slots a 45 s run can afford — every
fifteen minutes, forever, failing every time and crowding out users whose
mailboxes still work.

Marking rather than deleting, deliberately. Deleting the row is irreversible,
throws away the address the UI needs to say WHICH account to reconnect, and
would make an exception-type heuristic the trigger for destroying stored data.
A nullable timestamp is reversible: the OAuth callback's upsert clears it, so
reconnecting restores the user to the candidate list with no operator action.

Deploy
------

Both are plain nullable adds with no backfill: NULL is the honest default and
is exactly the state every existing row is already in ("no sync running", "not
revoked"). Additive, so one PR under docs/MIGRATIONS.md.

ORDER MATTERS HERE, unlike the index revision before it. Pushing to main starts
the migration workflow and a Vercel deploy at the same time and nothing orders
them; if the deploy wins, code that selects ``sync_state.sync_started_at``
reads a column the database does not have yet, and — because every
``select(...)`` in ``jobtracker.cloud`` emits an explicit column list — that is
an ``UndefinedColumn`` error, not a silently-missing field. The window is the
seconds until ``db-migrate`` lands and it self-heals, which is the trade-off
docs/MIGRATIONS.md already accepts for additive revisions. It is named here
rather than left to be discovered.

``batch_alter_table`` is for SQLite only; its default ``recreate="auto"`` leaves
Postgres on a plain ``ALTER TABLE ADD COLUMN``, so the RLS policies and FORCE
flags on both tables are untouched.
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f4c2a8e17b95"
down_revision: Union[str, Sequence[str], None] = "e7a1c4d92b30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add both nullable timestamps."""

    with op.batch_alter_table("sync_state", schema=None) as batch_op:
        batch_op.add_column(sa.Column("sync_started_at", sa.DateTime(), nullable=True))

    # ``timezone=True`` to match the other timestamps on this table (and the
    # model); ``sync_state``'s are naive, and each matches its own table.
    with op.batch_alter_table("user_credentials", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    """Drop them.

    Losing ``sync_started_at`` drops any lease in flight, which is the same
    state a TTL expiry produces and costs nothing. Losing ``revoked_at``
    silently re-admits revoked users to the cron's candidate list — they will
    fail on every run again, which is the behaviour this revision removed.
    """

    with op.batch_alter_table("user_credentials", schema=None) as batch_op:
        batch_op.drop_column("revoked_at")

    with op.batch_alter_table("sync_state", schema=None) as batch_op:
        batch_op.drop_column("sync_started_at")
