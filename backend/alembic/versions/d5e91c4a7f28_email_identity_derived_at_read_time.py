"""Store the application identity a message names, derived when it is read.

Revision ID: d5e91c4a7f28
Revises: c8f3a1d64b27
Create Date: 2026-08-23 05:30:00.000000

Adds ``emails.identity_role`` and ``emails.identity_req_id``.

Why
---

The classifier is handed the message BODY. Identity resolution was handed
``body_snippet``, which is Gmail's own ~200 characters, and every reader that
decides *which application a message is about* keyed off that one field. A job
title printed past character 200 was therefore invisible to the board while the
classifier read it perfectly.

Measured in the owner's mailbox on 2026-08-23: Torc Robotics prints
"the Software Engineer I - Metrics for Release opportunity" at body character
~380 and its card carried no position at all. The shipped extractor returns the
right answer the instant it is given the body — no pattern was missing, the
text never arrived.

Measured across the independent corpus once its harness was made
production-shaped: **50 applications split over two cards, 50 updates that
opened a rival card beside the one they belong on, and 452 updates that could
not be routed and were held for review.**

Why the value is stored rather than recomputed
----------------------------------------------

Deriving from the body and keeping the result in flight would have been worse
than the bug. ``pipeline.STORED_SNIPPET_CHARS`` records the failure it would
recreate: a key computed from one width of text when a decision is QUEUED and
another width when it is SETTLED leaves the row unlinked and un-reviewed, so it
is re-queued on every sync forever. That was measured on 2026-08-22, one layer
down, and an unpersisted body-derived token is the same mistake one layer up.

Storing it is what makes both sides of a decision read the same value.

Why this is not the body
------------------------

A job title and a requisition number are bounded, and ``applications.position``,
``applications.role_token`` and ``applications.req_id`` have stored exactly this
class of value since ``f1a2c9b73d40``. What changes is where the title is read
from, not what kind of thing is kept. ``/privacy`` says the body is read in
flight and discarded; that stays true, and
``tests/test_body_is_never_persisted.py`` places its sentinel immediately after
the capture boundary so a capture that ran long would drag the sentinel into
these columns and fail.

Design notes
------------

- Plain nullable adds, no index. No reader filters on either column; both are
  read alongside a row already being loaded by ``id``, ``user_id`` or
  ``message_id``.
- **NULL and empty string mean different things and the distinction is
  load-bearing.** NULL is "not derived on this row yet" — every row that exists
  when this migration runs, plus any row the client relay writes, since a relay
  item carries a snippet and no body and so knows nothing the reader cannot work
  out itself. Empty string is "derived, and the message names nothing", which is
  the normal permanent state for mail like Google's acknowledgement. Readers
  re-derive only for NULL; a single NULL could not answer both questions, and
  collapsing them would make a role phrase that spans a line break resolve one
  way in the body and another in Gmail's whitespace-joined snippet.
- **No backfill, deliberately.** A backfill could only read the stored ~200-char
  snippet, which is precisely the text the reader falls back to, so it would
  compute the same answer and buy nothing but a long write. Existing rows gain a
  real value the next time a scan reads them with a body, and every writer
  ratchets NULL upward and never blanks a value back down.
- Expand-only: two nullable columns, nothing dropped, nothing narrowed. Safe
  with the previous release still serving.
"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "d5e91c4a7f28"
down_revision: Union[str, Sequence[str], None] = "c8f3a1d64b27"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("emails", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "identity_role", sqlmodel.sql.sqltypes.AutoString(), nullable=True
            )
        )
        batch_op.add_column(
            sa.Column(
                "identity_req_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True
            )
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("emails", schema=None) as batch_op:
        batch_op.drop_column("identity_req_id")
        batch_op.drop_column("identity_role")
