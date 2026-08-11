"""application deadlines (due_at, due_source)

Revision ID: b7c31e0d94aa
Revises: f1a2c9b73d40
Create Date: 2026-08-11 20:10:00.000000

Adds ``applications.due_at`` / ``applications.due_source`` so the product can
keep the promise its own landing page opens with.

Why
---

The landing page's PROBLEM section leads with "The assessment scrolls past — its
48-hour deadline passes unseen." The application had no due-date field anywhere,
so an assessment email was classified into a column and then behaved exactly
like a rejection. The one failure mode the product names as its reason to exist
was the one it did nothing about.

Design notes
------------

- Both columns are plain nullable adds. NULL is the honest, permanent default:
  a deadline exists only because a message stated one or a human typed one, and
  it is never inferred. So every existing row is already in its correct state
  and the upgrade needs no backfill.
- ``due_source`` records WHO set it — ``mail`` or ``user`` — because the two are
  different claims and the sync treats them differently: it may refresh a
  ``mail`` deadline when later mail supersedes it, and must never touch one a
  human set. Storing the date without its origin would make that impossible and
  would leave the UI unable to say where a date came from.
- ``due_at`` is indexed: "what is due soon" is a filtered, ordered read on every
  dashboard load, and it is the query the feature exists to answer.
- ``batch_alter_table`` is for SQLite compatibility only. Its default
  ``recreate="auto"`` leaves Postgres on a plain ``ALTER TABLE ADD COLUMN``, so
  the RLS policies and the FORCE flag on ``applications`` are untouched.
- The downgrade drops both columns, which discards every deadline — including
  the ones a user typed by hand. That is real data loss, not a clean rollback.
"""
from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b7c31e0d94aa'
down_revision: Union[str, Sequence[str], None] = 'f1a2c9b73d40'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('applications', schema=None) as batch_op:
        batch_op.add_column(sa.Column('due_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('due_source', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch_op.create_index(batch_op.f('ix_applications_due_at'), ['due_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('applications', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_applications_due_at'))
        batch_op.drop_column('due_source')
        batch_op.drop_column('due_at')
