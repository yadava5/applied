"""a human decision carries no machine confidence (emails, data-only backfill)

Revision ID: a1c7f2e58b04
Revises: d3f5b81c6a72
Create Date: 2026-08-14 14:05:00.000000

Clears ``classification_confidence`` and rewrites ``classification_method`` to
``'user'`` on every row a human has already decided.

Why
---

``POST /applications/review/{message_id}/classify`` wrote ``classified_as``,
``is_reviewed`` and ``user_corrected`` and never touched the other two columns.
A row therefore kept the confidence and the method of the verdict it had just
replaced, and the Inbox drew them beside the human's category:

    rejection · 75% · corrected by you

The 75% was the classifier's certainty about ``applied``. Rendered next to a
verdict, a confidence figure is a claim about THAT verdict, so the row asserted
a probability nobody computed for a decision nobody scored — the
``classified_as`` defect family, where a stored value forges a decision that was
never made. The write site is fixed in ``cloud/applications.py``; this revision
repairs the rows that were written before it.

Design notes
------------

- DATA ONLY. No DDL: both columns are already nullable
  (``d7da4461f034`` created them ``nullable=True``), and ``'user'`` is already
  an accepted value in both ``ClassificationMethod`` and the ``CHECK`` in
  ``database/schema.sql``. Nothing about the schema changes, so
  ``scripts/check_expand_only.py`` has nothing to classify and the revision is
  additive by construction.
- NULL, not 1.0. 1.0 is a claim of total certainty on the same 0–1 scale the
  classifier reports on, drawn by the same ``GateMeter``; writing it would move
  the forgery from 75% to 100% rather than remove it. NULL is what is true —
  no probabilistic verdict exists for these rows.
- ``user_corrected`` is the predicate, not ``is_reviewed``. A row can be
  reviewed without being relabelled by a human, and only rows whose category
  came from a person may lose the classifier's number.
- Safe against every reader, checked one by one. Nothing selects a corrected
  row BY confidence: ``scripts/weekly_labeling_workflow.py`` and
  ``scripts/generate_ml_monitoring_report.py`` filter
  ``user_corrected.is_(False)`` before they compare the column, and so do
  ``api/classification.py``'s training-seed query (which additionally requires
  ``classification_method == "rules"``) and its needs-review list (which
  additionally requires ``classification_confidence != None``, so the
  ``or 0.0`` at its response site cannot fire on a NULL). The macOS review
  query in ``apps/macos/.../LocalDatabase.swift`` already excludes
  ``classification_confidence IS NULL``. So no row moves into or out of any
  queue as a result of this backfill.
- Idempotent. Re-running it selects the same rows and writes the same values.
- The downgrade CANNOT restore what this erases. The confidence figures being
  cleared were the machine's certainty about categories that
  ``classified_as = category`` had already overwritten at correction time, so
  the pre-correction verdict is not recoverable from this table and the numbers
  describe nothing that is still recorded. ``downgrade`` is therefore a no-op
  that says so, rather than a lie that writes 1.0 or re-invents ``'rules'``.
  Reversing this revision leaves the corrected rows correct; it is the upgrade
  that is one-way.

On the owner's production database this touches the 10 rows with
``user_corrected = true`` (4 of which were confirmations of the classifier's own
verdict rather than overrides — ``user_corrected`` does not distinguish the
two, which is noted in the PR and deliberately not changed here).
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1c7f2e58b04"
down_revision: Union[str, Sequence[str], None] = "d3f5b81c6a72"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# A minimal table construct rather than the SQLModel class: a migration must
# describe the schema AS OF THIS REVISION and must not drift when models.py
# changes underneath it.
emails = sa.table(
    "emails",
    sa.column("classification_confidence", sa.Float()),
    sa.column("classification_method", sa.String()),
    sa.column("user_corrected", sa.Boolean()),
)


def upgrade() -> None:
    """Strip the machine's number and method from every human-decided row."""
    # ``sa.true()`` and not a literal: SQLAlchemy renders it ``true`` on
    # Postgres and ``1`` on SQLite, and this revision runs against both (CI
    # builds its database from the migrations on each).
    op.execute(
        emails.update()
        .where(emails.c.user_corrected == sa.true())
        .values(classification_confidence=None, classification_method="user")
    )


def downgrade() -> None:
    """Deliberately a no-op — see the module docstring.

    The cleared figures were the classifier's confidence in categories this
    table no longer stores, so there is nothing to put back. Writing 1.0 or
    ``'rules'`` here would invent a verdict, which is the exact defect the
    upgrade exists to remove.
    """
