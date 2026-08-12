"""assessment becomes a real application status

Revision ID: b9e42f7c10ad
Revises: b7c31e0d94aa
Create Date: 2026-08-12 10:20:00.000000

Adds ``ASSESSMENT`` to the ``applicationstatus`` Postgres enum so the stage the
product now records is a stage the database can hold. The decision, and why it
reversed, is recorded in :data:`jobtracker.database.models.CATEGORY_TO_STATUS`;
this file is only the schema half of it.

Why the label is UPPERCASE
--------------------------

SQLModel/SQLAlchemy persist an enum's **name**, not its value. The initial
migration created

    sa.Enum('APPLIED', 'INTERVIEWING', ..., name='applicationstatus')

so the type's labels are the member names while the API speaks the lowercase
values. ``ADD VALUE 'assessment'`` would have succeeded as DDL and then failed
on every write with

    invalid input value for enum applicationstatus: "ASSESSMENT"

— a green migration followed by a 500. The SQLite suites cannot catch that:
``sa.Enum`` renders as ``VARCHAR`` there, so any label spelling round-trips.
``backend/tests/test_migrations_postgres.py`` runs this migration against a real
Postgres and asserts the labels equal ``[s.name for s in ApplicationStatus]`` in
order, which is the check that can actually fail.

``BEFORE 'INTERVIEWING'`` places the label at its lifecycle position in
``pg_enum``'s sort order, matching the enum's declaration order — cosmetic for
correctness, but it keeps ``ORDER BY status`` and any future
``enum_range()``-based query in lifecycle order rather than insertion order.

Why the autocommit block
------------------------

``backend/alembic/env.py`` wraps ALL pending revisions in ONE transaction (it
does not set ``transaction_per_migration``). A new enum label cannot be USED in
the transaction that added it — Postgres raises 55P04 "unsafe use of new value
of enum type". Nothing later in the current chain touches the label, so today
the hazard is latent rather than live; the block is here so the next revision
that does touch it (a backfill, a check constraint, a data migration) does not
have to discover this the hard way on a fresh environment running
``alembic upgrade head`` once. The preceding transaction is committed on entry,
which is safe here because this revision does nothing else.

Forward-only, like ``b7c31e0d94aa``
-----------------------------------

Postgres has no ``DROP VALUE``. The downgrade therefore remaps rows
(``ASSESSMENT`` → ``INTERVIEWING``, the fold this change undid) and leaves the
label in the type, inert. That loses the distinction the rows recorded — real
data loss, not a clean rollback, the same honesty the deadlines migration states
about dropping ``due_at``.

Two caveats on the downgrade, both about who runs it:

- ``applications`` has ``FORCE ROW LEVEL SECURITY`` (``a8d4ec5fba26``), so the
  UPDATE only touches rows the running role can see. Run it as the migration
  role (``DIRECT_URL``, i.e. the owner/superuser that bypasses RLS); a
  non-BYPASSRLS role would silently remap zero rows and report success.
- Re-running the upgrade afterwards is a no-op (``IF NOT EXISTS``), but it does
  NOT restore the remapped rows. There is nothing left to restore them from.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b9e42f7c10ad'
down_revision: Union[str, Sequence[str], None] = 'b7c31e0d94aa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_postgres() -> bool:
    """True when the current Alembic context targets PostgreSQL.

    Checked per-invocation rather than cached, matching ``a8d4ec5fba26``.
    """

    return op.get_context().dialect.name == "postgresql"


def upgrade() -> None:
    """Upgrade schema."""

    if not _is_postgres():
        # SQLite (desktop + tests) has no enum type to alter: `sa.Enum` renders
        # as VARCHAR with no CHECK constraint, so the new member is already
        # storable. A no-op keeps `alembic upgrade head` usable under both
        # dialects without branching in env.py.
        return

    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE applicationstatus "
            "ADD VALUE IF NOT EXISTS 'ASSESSMENT' BEFORE 'INTERVIEWING'"
        )


def downgrade() -> None:
    """Downgrade schema — lossy, and forward-only on the type itself."""

    # Runs on every dialect: the rows hold the enum NAME as text under SQLite
    # too, so a downgraded desktop install would otherwise keep a status its
    # code no longer knows.
    op.execute(
        "UPDATE applications SET status = 'INTERVIEWING' WHERE status = 'ASSESSMENT'"
    )
    # The 'ASSESSMENT' label deliberately STAYS in the Postgres type. There is
    # no `ALTER TYPE ... DROP VALUE`; dropping and recreating the type would
    # mean rewriting every dependent column and re-granting, to remove a label
    # that costs nothing while unused.
