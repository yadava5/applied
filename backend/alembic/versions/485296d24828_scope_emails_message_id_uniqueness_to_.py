"""scope emails message_id uniqueness to user_id

Revision ID: 485296d24828
Revises: c6_rls_initplan_hoist
Create Date: 2026-08-10 19:06:08.132434

De-globalizes ``emails.message_id``: the global UNIQUE becomes a composite
UNIQUE on ``(user_id, message_id)``.

Why
---

Every lookup of an email in the cloud path is already scoped by owner
(``WHERE user_id = :uid AND message_id = :mid`` — see
``jobtracker/cloud/applications.py``), but the column carried a *global*
unique index created by the initial revision ``d7da4461f034``. Two Supabase
users receiving the same Gmail message id — the same recruiter blast, the same
shared mailbox, a forwarded thread — is a legitimate multi-tenant case, and
under the global constraint the second user's INSERT raised a unique violation
that 500'd their entire sync.

This is the same shape of change ``6e64c46d32fd`` made to
``sync_state.account_email``, and the reason it was needed here too is simply
that its ``TABLES_WITH_USER_ID`` list never covered this column.

Design notes
------------

- Unlike ``sync_state.account_email`` (an inline, unnamed UNIQUE *constraint*
  that had to be reflected and dropped by its dialect-specific auto-generated
  name), ``emails.message_id``'s uniqueness is a named unique *INDEX*
  (``ix_emails_message_id``, created with ``unique=True``). Dropping and
  recreating an index is dialect-agnostic, so no reflection/naming-convention
  branching is needed and the whole migration is a single
  ``batch_alter_table`` block that runs identically on SQLite and Postgres.
- The single-column index is kept (non-unique) because the model still
  declares ``index=True`` on ``message_id``.
- The downgrade restores the global unique index. It will FAIL if, by then,
  two users legitimately hold the same message id — which is exactly the state
  this revision makes possible. That is inherent to reverting a
  de-globalization (``6e64c46d32fd``'s downgrade has the same property) and is
  preferable to silently dropping rows.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '485296d24828'
down_revision: Union[str, Sequence[str], None] = 'c6_rls_initplan_hoist'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('emails', schema=None) as batch_op:
        # Global UNIQUE → plain index (the model still wants it indexed).
        batch_op.drop_index(batch_op.f('ix_emails_message_id'))
        batch_op.create_index(
            batch_op.f('ix_emails_message_id'), ['message_id'], unique=False
        )
        # Uniqueness is now per owner.
        batch_op.create_index(
            'ix_emails_user_id_message_id', ['user_id', 'message_id'], unique=True
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('emails', schema=None) as batch_op:
        batch_op.drop_index('ix_emails_user_id_message_id')
        batch_op.drop_index(batch_op.f('ix_emails_message_id'))
        batch_op.create_index(
            batch_op.f('ix_emails_message_id'), ['message_id'], unique=True
        )
