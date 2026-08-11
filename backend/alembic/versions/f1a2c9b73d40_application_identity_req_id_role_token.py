"""application identity within an employer (req_id, role_token)

Revision ID: f1a2c9b73d40
Revises: e4cbb4aadccd
Create Date: 2026-08-11 01:40:00.000000

Adds ``applications.req_id`` / ``applications.role_token`` so an application is
identified by (employer, requisition-or-role) instead of by employer alone.

Why
---

Until now one company could hold exactly one application per user, by
construction: ``pipeline.roll_up_applications`` grouped gated mail on the
employer token and ``_find_application_by_token(...).first()`` resolved it to a
single row. On 2026-08-11 the owner's own mailbox showed what that costs — four
Amazon requisitions applied for in one evening (IDs 3177934, 3183020, 10414316,
3130865), two Anthropic roles and two Crusoe roles, rendered as three cards.
Five real applications were invisible.

It was also actively wrong, not merely coarse: a merged row takes the furthest
stage ANY of that company's mail reached, with a rejection as a terminal
override, and ``advance_application_status`` never moves a row out of a terminal
state. So the first per-requisition rejection would have settled the merged
Amazon row permanently and silently discarded every later interview or offer for
the other three.

Design notes
------------

- Both columns are plain nullable adds. ``NULL`` on both is a legitimate,
  permanent state meaning "this employer's mail names no role anywhere" —
  Supabase, Twitch and Together AI are all like that in the live corpus — and it
  is also the state every pre-existing row starts in, so the upgrade needs no
  backfill and changes nothing a user sees until the next sync.
- Existing rows are adopted IN PLACE on that next sync rather than rewritten
  here: ``_resolve_application`` matches a cluster to the employer's single
  identity-less row and stamps the identity onto it, which keeps the row id and
  therefore every contact, interview, linked email and user correction attached
  to it. Doing the split in SQL would have had to guess the same thing with less
  information, and would not have been undoable.
- **No unique constraint on (user_id, company, req_id).** Re-applying to the
  same requisition after a rejection is a second application, and the resolver
  only ever matches live rows. A unique index would forbid the legitimate case
  to prevent one the resolver already prevents.
- ``req_id`` is indexed because the resolver looks rows up by it on every sync;
  ``role_token`` is not, because it is only ever compared within the handful of
  rows already fetched for one employer.
- ``batch_alter_table`` is for SQLite compatibility only. Its default
  ``recreate="auto"`` leaves Postgres on a plain ``ALTER TABLE ADD COLUMN``, so
  the RLS policies and the FORCE flag on ``applications`` are untouched.
- The downgrade drops both columns. Rows survive it, but the employer's
  applications become indistinguishable again and the next sync will re-merge
  them, so it is a real loss of structure rather than a clean rollback.
"""
from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f1a2c9b73d40'
down_revision: Union[str, Sequence[str], None] = 'e4cbb4aadccd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('applications', schema=None) as batch_op:
        batch_op.add_column(sa.Column('req_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch_op.add_column(sa.Column('role_token', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch_op.create_index(batch_op.f('ix_applications_req_id'), ['req_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('applications', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_applications_req_id'))
        batch_op.drop_column('role_token')
        batch_op.drop_column('req_id')
