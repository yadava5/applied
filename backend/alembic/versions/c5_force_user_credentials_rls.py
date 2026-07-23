"""FORCE row level security on user_credentials (postgres-only)

Revision ID: c5_force_user_creds_rls
Revises: c4user_creds_rls
Create Date: 2026-07-23 00:00:00.000000

Closes the enforcement gap left by ``c4user_creds_rls``. That revision
``ENABLE``d RLS on ``user_credentials`` and installed the four owner
policies, but never issued ``ALTER TABLE ... FORCE ROW LEVEL SECURITY``.
Without ``FORCE``, RLS is silently *bypassed for the table owner* — and
the application historically connected as the owning ``postgres`` role
(``rolbypassrls = true``), so the policies enforced nothing in
production. The sibling entity tables (``applications``, ``emails``,
``contacts``, ``interviews``, ``training_data``, ``email_embeddings``,
``sync_state``) were already both ``ENABLE``d **and** ``FORCE``d in
revision ``a8d4ec5fba26``; ``user_credentials`` was the sole table left
un-``FORCE``d. This revision brings it into line so the encrypted Gmail /
iCloud token rows are subject to the owner policies too.

``FORCE`` matters in tandem with the production cutover to a dedicated
non-``BYPASSRLS`` application role: even the table owner is then held to
the policies, so ``request.jwt.claims`` (set per transaction by the app)
is the *only* way to read or write a user's credential row.

Postgres-only and dialect-gated: SQLite (desktop + CI) has no RLS
machinery, so ``upgrade``/``downgrade`` are no-ops there, keeping
``alembic upgrade head`` green under SQLite.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "c5_force_user_creds_rls"
down_revision: Union[str, Sequence[str], None] = "c4user_creds_rls"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_postgres() -> bool:
    """True when the current Alembic context targets PostgreSQL."""

    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    # RLS was already ENABLEd + policied in c4user_creds_rls; only FORCE was
    # missing. FORCE subjects the table owner to the policies as well.
    op.execute("ALTER TABLE user_credentials FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute("ALTER TABLE user_credentials NO FORCE ROW LEVEL SECURITY")
