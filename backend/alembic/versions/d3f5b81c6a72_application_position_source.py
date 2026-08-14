"""a user-supplied role (applications.position_source)

Revision ID: d3f5b81c6a72
Revises: c2e7f4a91b83
Create Date: 2026-08-14 10:20:00.000000

Adds ``applications.position_source`` so a job title a human typed can be told
apart from one the sync wrote, and protected from the next sync.

Why
---

Issue #72. Every application filed from Gmail lands with ``position = ""``, for
two reasons that no amount of extraction work fixes from where it stands:
``cloud/gmail_client.py`` batch-fetches with ``format=metadata`` so bodies are
never read, and the ATS acknowledgement subjects that ARE read name the employer
rather than the role — "Thanks for applying to Supabase", "Thank you for
applying with MotherDuck!", "Thank you for applying to Anthropic" all extract
``None``. The chosen answer is to let the user fill the role in and remember it,
which needs somewhere to record that the field is now theirs.

Design notes
------------

- One plain nullable add. NULL is the honest, permanent default and means "the
  sync owns this field" — the state every existing row is already in — so the
  upgrade needs no backfill and no row changes meaning.
- ``position_source`` rather than reusing ``source``.
  ``record_status_correction`` makes a STATUS sticky by flipping ``source``
  from ``gmail`` to ``gmail_user``, and that was available here for free. It is
  the wrong tool: ``_is_auto_row(source)`` also gates the status advance, the
  reopen-after-rejection evidence and the employer-name restyle, all inside one
  ``if`` in ``upsert_applications_for_user``. Reusing it would mean that typing
  a job title silently stopped every later rejection or interview email from
  moving that card. ``due_source`` is the precedent that fits — per-field
  provenance, claiming exactly one field.
- Only two values are ever written: NULL and ``'user'``. There is no ``'mail'``
  counterpart even though ``due_source`` has one, because the only question
  asked of this column is "may the sync write here?", and a value stamped at
  four creation sites to answer a question nobody asks is four places to drift.
- Not indexed. It is read on rows already in hand during an upsert, never
  filtered on.
- ``batch_alter_table`` is for SQLite compatibility only. Its default
  ``recreate="auto"`` leaves Postgres on a plain ``ALTER TABLE ADD COLUMN``, so
  the RLS policies and the FORCE flag on ``applications`` are untouched.
- Additive, so it is a one-PR revision under docs/MIGRATIONS.md: whichever of
  the migration workflow and the Vercel deploy lands first, both halves work.
- The downgrade drops the column, which discards the record of WHICH roles were
  typed by a human. The titles themselves survive in ``position``, but the next
  sync becomes free to overwrite them — so this is data loss with a delay, not a
  clean rollback.
"""
from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd3f5b81c6a72'
down_revision: Union[str, Sequence[str], None] = 'c2e7f4a91b83'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('applications', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('position_source', sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('applications', schema=None) as batch_op:
        batch_op.drop_column('position_source')
