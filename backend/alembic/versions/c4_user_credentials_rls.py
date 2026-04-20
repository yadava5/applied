"""enable RLS on user_credentials (postgres-only)

Adds the ``auth.users(id)`` foreign key and RLS policies on
``user_credentials``. Both are Postgres-only and gated on the
dialect; SQLite runs this migration as a no-op.

Mirrors the pattern from revision ``a8d4ec5fba26`` (RLS on the
entity tables introduced in C3).

Revision ID: c4user_creds_rls
Revises: 22cefa34bc94
Create Date: 2026-04-20 07:55:00.000000

"""

from typing import Sequence, Union

from alembic import op


revision: str = "c4user_creds_rls"
down_revision: Union[str, Sequence[str], None] = "22cefa34bc94"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_POSTGRES_UPGRADE_SQL = """
ALTER TABLE user_credentials
    ADD CONSTRAINT fk_user_credentials_user_id
    FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;

ALTER TABLE user_credentials ENABLE ROW LEVEL SECURITY;

CREATE POLICY user_credentials_owner_select ON user_credentials
    FOR SELECT USING (user_id = auth.uid());

CREATE POLICY user_credentials_owner_insert ON user_credentials
    FOR INSERT WITH CHECK (user_id = auth.uid());

CREATE POLICY user_credentials_owner_update ON user_credentials
    FOR UPDATE USING (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());

CREATE POLICY user_credentials_owner_delete ON user_credentials
    FOR DELETE USING (user_id = auth.uid());
"""

_POSTGRES_DOWNGRADE_SQL = """
DROP POLICY IF EXISTS user_credentials_owner_delete ON user_credentials;
DROP POLICY IF EXISTS user_credentials_owner_update ON user_credentials;
DROP POLICY IF EXISTS user_credentials_owner_insert ON user_credentials;
DROP POLICY IF EXISTS user_credentials_owner_select ON user_credentials;

ALTER TABLE user_credentials DISABLE ROW LEVEL SECURITY;

ALTER TABLE user_credentials DROP CONSTRAINT IF EXISTS fk_user_credentials_user_id;
"""


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite desktop/CI: skip. The FK to auth.users does not
        # exist in SQLite and RLS has no analog there.
        return
    op.execute(_POSTGRES_UPGRADE_SQL)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(_POSTGRES_DOWNGRADE_SQL)
