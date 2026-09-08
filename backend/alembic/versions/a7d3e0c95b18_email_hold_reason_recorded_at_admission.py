"""Record WHY the review queue holds a message, when the read path cannot tell.

Revision ID: a7d3e0c95b18
Revises: f1c47b93a2d6
Create Date: 2026-09-08 09:00:00.000000

Adds ``emails.hold_reason``.

Why
---

Issue #800. A long-form offer withdrawal — one whose own text is long enough to
survive quote-stripping, so #417's retraction cap never sees it — classifies
``other`` at 0.50. That is below ``pipeline.REVIEW_FLOOR``, so the sync path
discarded it: no ``emails`` row, no queue entry, and the offer it cancels still
filed on the board. Reproduced at HEAD::

    long-form withdrawal -> OTHER 0.50  matched: ['[NEGATIVE] offer',
                                                  '[NEGATIVE] offer']

The fix admits that message to the human review queue when the employer it names
holds a live ``OFFERED`` card. It does NOT lift the confidence — the stored value
stays 0.50 — so the row arrives in the queue looking exactly like any other
sub-floor message, and something has to say why it is there.

Why the reason is stored rather than re-derived
-----------------------------------------------

``pipeline.hold_reason`` computes the other eight reasons at read time, from the
same functions the sync used to hold the row, and for those eight that is
correct: their operands are the message, and a message does not change.

``contradicts_filed`` is the exception, and the difference is not stylistic. Its
operands are the message AND A CARD ON THE BOARD. The card moves — an offer can
be accepted, dismissed, or advanced by hand between the sync that admitted the
message and the read that describes it. A re-derivation that looked for the card
and no longer found it would explain the row as ``below_gate``, "the classifier
was unsure", about a message admitted precisely because something else was
certain.

That is #507's defect rebuilt one layer down: the web used to infer the hold
sentence from the confidence score alone and printed a plausible sentence in
place of a true one, wrong on all three rows it appeared on. Storing the reason
is what makes the sentence the queue shows and the decision the sync made the
same fact.

The same column is what the additive persist's settled filter reads to exempt a
contradiction from suppression, so one field serves both halves of the fix
rather than two fields drifting apart.

Design notes
------------

- Plain nullable add, no index. No reader filters on it; it is read alongside a
  row already being loaded by ``user_id`` and ``message_id``.
- **NULL means "no admission-time reason was recorded"** — every row that exists
  when this migration runs, and every row admitted by one of the other eight
  routes, which have nothing to record. Readers derive a reason only for NULL,
  so no existing queue row changes the sentence it shows.
- **No backfill, and unlike ``d5e91c4a7f28`` not even a lossy one is possible.**
  The fact this column records is "an ``OFFERED`` card existed at the moment this
  message was admitted". That moment is gone, and the board's present state is
  not evidence about it. A backfill could only guess, and a guessed provenance is
  worse than an absent one.
- **Not mail content.** The column holds one of a closed set of ASCII tokens
  defined in ``pipeline.HOLD_REASONS``; no subject, snippet or employer name
  reaches it. ``/privacy``'s claim that the body is read in flight and discarded
  is untouched, and ``tests/test_body_is_never_persisted.py``'s sentinel sits
  past the capture boundary and would fail if one did.
- Expand-only: one nullable column, nothing dropped, nothing narrowed. Safe with
  the previous release still serving — it neither writes nor reads the column,
  and NULL is exactly the value its behaviour corresponds to.
"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "a7d3e0c95b18"
down_revision: Union[str, Sequence[str], None] = "f1c47b93a2d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("emails", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("hold_reason", sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("emails", schema=None) as batch_op:
        batch_op.drop_column("hold_reason")
