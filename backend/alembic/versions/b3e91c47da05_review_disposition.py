"""agreement and override stop being the same row

Revision ID: b3e91c47da05
Revises: e2b6f0a4d517
Create Date: 2026-08-14 18:40:00.000000

Adds ``emails.review_disposition``, nullable, over a new ``reviewdisposition``
enum type — and backfills every pre-existing human decision to ``UNKNOWN``,
which is a statement about what is not knowable rather than a label.

Why
---

``POST /applications/review/{message_id}/classify`` wrote::

    email.classified_as = category
    email.is_reviewed = True
    email.user_corrected = True

unconditionally. A human who AGREES with the classifier's verdict and a human
who OVERRULES it therefore produced byte-identical rows, and ``classified_as``
had already overwritten the machine's verdict in place, so nothing on the row
could tell them apart afterwards either.

Every "the classifier was wrong N times" figure built on ``user_corrected`` is
inflated by an unknown amount, and inflated in the direction that makes the
classifier look worse than it is. It also polluted the training signal: a
confirmation and an override are different evidence stored as the same thing.

It reached a reader. An audit read production, saw ``user_corrected = true`` on
every REJECTION row, and concluded — and reported — that the classifier had
never once auto-detected a rejection. That was false. Replayed through the real
classifier the Palantir message returns ``rejection`` at 0.75: the correct
category, held under the 0.85 auto-file gate for review, where the human agreed
with it. Two rows reading ``Crusoe | Application Received`` at 0.95 carry the
same flag, and nobody corrects an acknowledgement the machine already had at
0.95.

The existing rows are NOT recoverable, and are not guessed
----------------------------------------------------------

There is no honest way to separate the ten flagged rows retroactively. The
machine's verdict was overwritten by the correction itself, so it is not in this
table; replaying today's classifier over them would reconstruct a verdict that
today's classifier produces rather than the one that was actually shown, which
is forging the label in the other direction. A missing label stays missing. A
fabricated one looks like data and gets counted.

So this revision writes ``UNKNOWN`` on them, which is the third state
:class:`~jobtracker.database.models.ReviewDisposition` exists to make sayable:
*a human decision is on record here and which act it was cannot be recovered,
because the row was written before the distinction existed*. It is not a guess,
it is not a default, and it is not NULL — NULL already means "no human decision
recorded", which is a different and equally true fact about a different set of
rows.

``UNATTRIBUTED`` is deliberately a separate value and this revision never
writes it. It is a LIVE case — a message minted through ``ScannedMessageIn``
with ``category=None`` has no verdict for a human to agree or disagree with —
and folding the two together would make the count of rows damaged by this defect
unrecoverable the moment the backfill ran.

Design notes
------------

- **Additive only.** ``CREATE TYPE`` + ``ADD COLUMN`` + one ``UPDATE``. Nothing
  is dropped, narrowed or retyped, so ``scripts/check_expand_only.py`` has
  nothing to classify.
- **``user_corrected`` is untouched, in the schema and in its meaning.** It
  keeps reading "a human settled this row". Four queries filter
  ``user_corrected.is_(False)`` as their definition of not-yet-settled
  (``scripts/weekly_labeling_workflow.py`` ×2,
  ``scripts/generate_ml_monitoring_report.py`` ×2) and none of them also filters
  ``is_reviewed``, so narrowing the flag to overrides-only would push every
  AGREEMENT back into the weekly labeling queue and into the needs-review count
  — a row whose label a human already settled, leading the queue. That is the
  trap ``_settle_thread_siblings`` documents for thread siblings, in a louder
  form. This revision therefore moves no row into or out of any queue.
- **The type is CREATED here**, unlike ``c2e7f4a91b83`` which reused
  ``emailcategory``. ``reviewdisposition`` does not exist yet, so
  ``checkfirst=True`` creates it on Postgres and the SQLite path renders
  ``sa.Enum`` as VARCHAR with no type to create. A new type is not the
  ``ALTER TYPE ... ADD VALUE`` hazard ``b9e42f7c10ad`` documents: 55P04 covers
  values ADDED to an existing type, so the backfill below may use the labels in
  the same transaction that created them, and no ``autocommit_block`` is needed.
- **Labels are the member NAMES, uppercase.** SQLModel/SQLAlchemy persist an
  enum's name, not its value — the same rule ``b9e42f7c10ad`` was written to
  record — so the type holds ``'UNKNOWN'`` while the API speaks ``"unknown"``.
  The backfill writes the uppercase spelling for that reason; the lowercase one
  would be a green migration followed by a 500.
- **No index.** Nothing filters on this column and nothing should start; an
  index would also read as drift against the SQLModel metadata.
- ``batch_alter_table`` is for SQLite only. Its default ``recreate="auto"``
  leaves Postgres on a plain ``ALTER TABLE ADD COLUMN``, so the RLS policies and
  the FORCE flag on ``emails`` (``a8d4ec5fba26``) are untouched.
- **Idempotent.** Re-running selects the same rows and writes the same value —
  except that a row already carrying ``CONFIRMED`` or ``OVERRIDDEN`` is excluded
  by the ``IS NULL`` predicate, so a re-run can never overwrite a real
  disposition with ``UNKNOWN``.
- **Run it as the migration role.** ``emails`` has ``FORCE ROW LEVEL SECURITY``,
  so the UPDATE only touches rows the running role can see. Under ``DIRECT_URL``
  (the owner) that is all of them; a NOBYPASSRLS role would report success
  having updated nothing.
- The downgrade is clean. Dropping the column loses dispositions recorded after
  this revision and puts the rows back in exactly the ambiguous state this
  revision found them in, which is what a rollback of this change means.

On the owner's production database the backfill touches the 10 rows with
``user_corrected = true``, at least 4 of which are known confirmations.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3e91c47da05"
down_revision: str | Sequence[str] | None = "e2b6f0a4d517"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Declaration order, member NAMES, verbatim from
# ``jobtracker.database.models.ReviewDisposition``. Spelled out here rather than
# imported: a migration must describe the type AS OF THIS REVISION and must not
# drift when models.py changes underneath it.
REVIEW_DISPOSITION_LABELS = (
    "CONFIRMED",
    "OVERRIDDEN",
    "UNATTRIBUTED",
    "UNKNOWN",
)


def _is_postgres() -> bool:
    """True when the current Alembic context targets PostgreSQL.

    Checked per-invocation rather than cached, matching ``a8d4ec5fba26``.
    """

    return op.get_context().dialect.name == "postgresql"


def _review_disposition_type() -> sa.types.TypeEngine[str]:
    """The ``reviewdisposition`` type — created by this revision, not reused."""

    if _is_postgres():
        return postgresql.ENUM(*REVIEW_DISPOSITION_LABELS, name="reviewdisposition")
    # SQLite (desktop + tests): ``sa.Enum`` renders as VARCHAR with no CHECK
    # constraint, so there is no type to create and nothing to collide with.
    return sa.Enum(*REVIEW_DISPOSITION_LABELS, name="reviewdisposition")


def _emails(enum_type: sa.types.TypeEngine[str]) -> sa.TableClause:
    """A minimal table construct rather than the SQLModel class.

    Same reason the labels are spelled out above: a migration must describe the
    schema AS OF THIS REVISION and must not drift when models.py changes.

    Built per-call and TYPED WITH THE ENUM, which is not cosmetic. Declared as
    ``sa.String()`` the update below compiles to
    ``SET review_disposition = $1::VARCHAR``, and Postgres refuses it:

        DatatypeMismatch: column "review_disposition" is of type
        reviewdisposition but expression is of type character varying

    SQLite renders ``sa.Enum`` as VARCHAR and accepts the string either way, so
    the SQLite suites are green on the broken version — this failed only under
    ``tests/test_migrations_postgres.py``, which runs the chain against a real
    postgres:16. That is the ``b9e42f7c10ad`` shape exactly: a migration that
    passes everywhere except the one dialect production runs on.
    """

    return sa.table(
        "emails",
        sa.column("review_disposition", enum_type),
        sa.column("user_corrected", sa.Boolean()),
    )


def upgrade() -> None:
    """Add the column, then say ``UNKNOWN`` about every decision already made."""

    enum_type = _review_disposition_type()
    if _is_postgres():
        # ``add_column`` does not reliably emit ``CREATE TYPE`` for a type it has
        # not seen; create it explicitly so a re-run and a from-empty build both
        # work.
        enum_type.create(op.get_bind(), checkfirst=True)

    with op.batch_alter_table("emails", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("review_disposition", enum_type, nullable=True)
        )

    emails = _emails(enum_type)
    # ``sa.true()`` and not a literal: SQLAlchemy renders it ``true`` on Postgres
    # and ``1`` on SQLite, and this revision runs against both (CI builds its
    # database from the migrations on each).
    #
    # The ``IS NULL`` arm is what makes a re-run safe. It is redundant on the
    # first pass — the column was created one statement ago — and load-bearing
    # on every pass after it.
    op.execute(
        emails.update()
        .where(emails.c.user_corrected == sa.true())
        .where(emails.c.review_disposition.is_(None))
        .values(review_disposition="UNKNOWN")
    )


def downgrade() -> None:
    """Drop the column and the type, returning the rows to their ambiguity."""

    with op.batch_alter_table("emails", schema=None) as batch_op:
        batch_op.drop_column("review_disposition")

    if _is_postgres():
        # Unlike ``b9e42f7c10ad``'s label, a whole type CAN be dropped, and this
        # one has exactly one dependent column — just removed. Left behind it
        # would collide with the ``CREATE TYPE`` on the next upgrade.
        postgresql.ENUM(name="reviewdisposition").drop(op.get_bind(), checkfirst=True)
