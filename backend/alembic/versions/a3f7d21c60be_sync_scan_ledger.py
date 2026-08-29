"""what the last sync looked at, and where every message went

Revision ID: a3f7d21c60be
Revises: d5e91c4a7f28
Create Date: 2026-08-29 10:00:00.000000

Six nullable integers on ``sync_state``, for one question the database could
not answer: **did we see your mail?**

The report (#422)
-----------------

"I applied to 4 new Microsoft and a Google application, but when I sync it in
the app, I'm not getting anything." The four Microsoft confirmations produced
zero rows anywhere — no ``emails`` row, no application, nothing in the review
queue. ``_persist_message_refs`` writes an ``emails`` row only for a message
that clustered into an application or was flagged for review, so a message the
pipeline discarded leaves the database exactly as a message that never arrived
does. From Postgres, with full access, these three were indistinguishable:

  * the mail never reached the mailbox,
  * it arrived after ``last_sync_at`` and is simply not synced yet,
  * it was fetched, scored, and thrown away.

Diagnosing which took a mailbox read and a local reproduction of the pipeline.

What these columns are
----------------------

The ledger of the last SUCCESSFUL sync, one partition that closes::

    last_classified == last_filed + last_queued + last_dropped
                                  + last_reached_nothing

``last_scanned`` sits outside it and is the wider number — what the scan read
from Gmail, before anything was dropped ahead of the pipeline (the user's own
sent mail, which ``_classify_messages`` skips, and a repeated message id, since
the ledger counts distinct ones). See ``pipeline.ScanLedger`` for what each
bucket means and why ``reached_nothing`` is the product-computable superset of
the corpus harness's ``LOST``.

Written by ``cloud/sync_state.record_gmail_sync_success`` in the same unit of
work as ``last_sync_at``, and read back by ``GET /auth/gmail/status``. The same
``ScanLedger`` populates ``POST /gmail/sync``'s response, so the durable row and
the response cannot report different numbers.

Counts, and nothing else
------------------------

No message id, no subject, no sender. Applied is a privacy-sensitive product
and ``apps/web/app/(app)/privacy/page.tsx`` publishes the whole ``emails`` row;
keeping mail metadata for messages the product decided NOT to file would
contradict it. An integer cannot. What was dropped is already in the logs,
keyed by message id, where it is bounded by retention rather than kept forever.

NULL is not zero
----------------

Every existing row gets NULL, which is the honest state: no sync has recorded a
ledger yet. Zero means something different and stronger — a sync ran and read
nothing — and the reader must be able to tell them apart, so there is no
backfill and no server default.

Deploy
------

Plain nullable adds, no backfill: additive, so one PR under docs/MIGRATIONS.md.

ORDER, as ``f4c2a8e17b95`` states it: pushing to main starts ``db-migrate`` and
a Vercel deploy at the same time and nothing orders them. If the deploy wins,
code that selects ``sync_state.last_scanned`` reads a column the database does
not have yet, and because every ``select(...)`` in ``jobtracker.cloud`` emits an
explicit column list that is an ``UndefinedColumn`` error rather than a missing
field. The window is the seconds until the workflow lands and it self-heals;
that is the trade-off docs/MIGRATIONS.md already accepts for additive
revisions. Named here rather than left to be discovered.

WHAT A USER SEES IN THAT WINDOW, measured against an un-migrated database with
the new code rather than reasoned from it, because "an UndefinedColumn error"
does not say who pays for it:

  * ``GET /auth/gmail/status`` selects the row unconditionally and has no
    handler for the failure, so it is a **500 for every connected user** until
    the workflow lands. The settings and inbox screens both fetch it.
  * ``POST /gmail/sync`` splits on whether the caller already HAS a
    ``sync_state`` row. A first-time syncer has none, so
    ``acquire_gmail_sync_lease``'s conditional UPDATE matches nothing, it falls
    through to ``load_gmail_sync_state``, and the request 500s before any mail
    is touched. Harmless.
  * A returning user's lease UPDATE matches — an UPDATE names no columns, so it
    cannot trip this — and the run proceeds. ``sync_gmail_pipeline_additive``
    COMMITS the filed mail, and only then does ``record_gmail_sync_success``
    select the row and raise. So the mail **is filed**, the cursor is **not**
    advanced, the user gets a 500, and ``InboxWorkbench`` renders "Couldn't file
    these (500) — nothing was changed." That sentence is false, and it is the
    one outcome here worth writing down.
  * ``note_gmail_sync_failure`` reads the same row, so it cannot record the
    failure either: ``sync_state.status`` keeps whatever it said before.

None of this is corruption — the next sync re-files idempotently over
``UNIQUE ix_emails_user_id_message_id`` — and none of it is new to this
revision; any additive column on ``sync_state`` has the same shape. Catching
``UndefinedColumn`` on the status read would trade a 500 for "ledger unknown"
but would not touch the false message above, which is on the sync path and
whose only real fix is returning 200 after a failed ledger write — the failure
mode this revision deliberately keeps (a ledger that cannot be written must not
advance ``last_sync_at``). Filed rather than built.

``batch_alter_table`` is for SQLite only; its default ``recreate="auto"`` leaves
Postgres on a plain ``ALTER TABLE ADD COLUMN``, so the RLS policies and FORCE
flag on ``sync_state`` (revision ``a8d4ec5fba26``) are untouched.
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3f7d21c60be"
down_revision: Union[str, Sequence[str], None] = "d5e91c4a7f28"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


#: The ledger, in the order the partition reads. ``last_scanned`` first because
#: it is the outer number; the four that must sum to ``last_classified`` follow
#: it, so a ``\d sync_state`` reads as the accounting it is.
_LEDGER_COLUMNS = (
    "last_scanned",
    "last_classified",
    "last_filed",
    "last_queued",
    "last_dropped",
    "last_reached_nothing",
)


def upgrade() -> None:
    """Add the six nullable counters."""

    with op.batch_alter_table("sync_state", schema=None) as batch_op:
        for name in _LEDGER_COLUMNS:
            batch_op.add_column(sa.Column(name, sa.Integer(), nullable=True))


def downgrade() -> None:
    """Drop them.

    Losing these costs the diagnosis they exist for and nothing else: no code
    path branches on them, and a sync whose ledger cannot be written is still a
    sync that filed its mail.
    """

    with op.batch_alter_table("sync_state", schema=None) as batch_op:
        for name in reversed(_LEDGER_COLUMNS):
            batch_op.drop_column(name)
