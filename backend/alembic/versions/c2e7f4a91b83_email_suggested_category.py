"""a slot for the classifier's PROPOSAL, distinct from the commitment

Revision ID: c2e7f4a91b83
Revises: b9e42f7c10ad
Create Date: 2026-08-12 15:40:00.000000

Adds ``emails.suggested_category``, nullable, over the existing ``emailcategory``
type. Schema half only; the reasoning lives here because the column is
indistinguishable from a mistake without it.

Why a second column and not the one we already have
---------------------------------------------------

``emails.classified_as`` does not mean "what this mail is". It means the
COMMITTED category — the one the system is allowed to act on — and
``NEEDS_REVIEW`` is its typed null:

- ``classify_review_item`` writes it only when a human commits;
- ``tracking/linker.py:237`` reads ``NEEDS_REVIEW`` as "no committed category,
  never act";
- ``reconcile_orphaned_classifications`` files applications from it with
  ``source=SOURCE_GMAIL_USER``, i.e. human-owned.

So the obvious fix for the real defect — a rejection from an ATS relay whose
employer cannot be named is parked in the review queue with its verdict
hardcoded away — was to carry the real category into ``classified_as``. That
was tried and measured: 700 passing became 9 failing, and those 9 were the
design working. Writing a verdict there for a parked row does not record a
verdict, it FORGES A COMMITMENT.

The actual gap is that there was a slot for the commitment and a slot for the
queue state, and no slot for the proposal. The row already stored the
proposal's strength: production rows read "needs_review at 0.92", the
confidence of an opinion whose content had been deleted. This column is where
the content goes.

``classified_as`` values are always assertions. ``suggested_category`` values
are always proposals. No existing reader's predicate changes — not the queue,
not the summary counts, not ``api/classification.py``, not the linker, not the
macOS local count. That is the property that makes the column safe to add.

Design notes
------------

- **NULL is the normal, permanent state** for every pre-existing row and for
  every row that has a commitment. No backfill: a parked row picks its
  suggestion up in place on the next sync that covers it, because
  ``_persist_message_refs`` re-writes un-settled rows.
- **``needs_review`` is never stored here.** The column holds one of the eight
  predicted labels or NULL. A below-gate ``needs_review`` leaking in would
  recreate a frozen-forever row of the kind ``docs/ML_CORPUS_INTEGRITY.md``
  records. The eight-value restriction is enforced in the writer, not in the
  type — the type is shared with ``classified_as``, which legitimately holds
  all nine.
- **The existing ``emailcategory`` type is REUSED, not recreated.** On Postgres
  a bare ``sa.Enum(..., name='emailcategory')`` in ``add_column`` emits
  ``CREATE TYPE`` and fails with *type "emailcategory" already exists* — and
  the SQLite suites cannot see it, because ``sa.Enum`` renders as VARCHAR
  there. That is exactly the trap ``b9e42f7c10ad`` documents, so this revision
  branches on the dialect the same way: ``postgresql.ENUM(..., create_type=
  False)`` on Postgres, plain ``sa.Enum`` (→ VARCHAR) everywhere else.
- Labels are the member NAMES, uppercase, copied verbatim from
  ``d7da4461f034``. SQLModel/SQLAlchemy persist an enum's name, not its value,
  so the type's labels are uppercase while the API speaks the lowercase values.
- **No index.** Nothing filters on this column by design; an index here would
  also show up as drift against the SQLModel metadata.
- ``batch_alter_table`` is for SQLite compatibility only. Its default
  ``recreate="auto"`` leaves Postgres on a plain ``ALTER TABLE ADD COLUMN``, so
  the RLS policies and the FORCE flag on ``emails`` (``a8d4ec5fba26``) are
  untouched.
- The downgrade is clean: dropping the column loses suggestions that the next
  sync regenerates, and no other state depends on it.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c2e7f4a91b83'
down_revision: Union[str, Sequence[str], None] = 'b9e42f7c10ad'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The nine labels of the existing ``emailcategory`` type, in declaration order,
# verbatim from ``d7da4461f034``. Not re-derived from the Python enum: this
# revision must describe the type as it EXISTS, not as the model happens to
# define it today.
EMAIL_CATEGORY_LABELS = (
    'APPLIED',
    'PENDING_APPLICATION',
    'INTERVIEW',
    'REJECTION',
    'OFFER',
    'ASSESSMENT',
    'FOLLOW_UP',
    'NEEDS_REVIEW',
    'OTHER',
)


def _email_category_type() -> sa.types.TypeEngine[str]:
    """The ``emailcategory`` type, reused rather than created.

    Checked per-invocation rather than cached, matching ``b9e42f7c10ad``.
    """

    if op.get_context().dialect.name == "postgresql":
        return postgresql.ENUM(
            *EMAIL_CATEGORY_LABELS, name="emailcategory", create_type=False
        )
    # SQLite (desktop + tests): ``sa.Enum`` renders as VARCHAR with no CHECK
    # constraint, so there is no type to reuse and nothing to collide with.
    return sa.Enum(*EMAIL_CATEGORY_LABELS, name="emailcategory")


def upgrade() -> None:
    """Upgrade schema."""

    with op.batch_alter_table('emails', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('suggested_category', _email_category_type(), nullable=True)
        )


def downgrade() -> None:
    """Downgrade schema."""

    with op.batch_alter_table('emails', schema=None) as batch_op:
        batch_op.drop_column('suggested_category')
