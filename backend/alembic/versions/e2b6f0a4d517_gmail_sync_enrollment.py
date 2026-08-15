"""gmail_sync_enrollment — publish the membership fact, without the secret

Revision ID: e2b6f0a4d517
Revises: a9d3e5f2c841
Create Date: 2026-08-14 16:40:00.000000

WHAT THIS IS FOR (issue #291)
-----------------------------

The scheduled Gmail sync only acts for users named in
``JOBTRACKER_CRON_SYNC_USER_IDS``. A new user therefore gets no background sync
until a human edits Vercel configuration and redeploys — it breaks at user #3,
not at scale.

The env var exists for a real reason and the reason is still true: the cron
carries no JWT, ``user_credentials`` is FORCE-RLS on ``auth.uid()``, and an
identity-less ``SELECT`` over it correctly returns nothing.

But the cron does not need to read ``user_credentials``. It needs the set of
user ids that hold a Gmail credential. That is a membership fact, and it can
live somewhere that holds no secret at all:

    gmail_sync_enrollment(user_id uuid primary key, enrolled_at timestamptz)

No ciphertext. No email address. No ``kind``. The leak this whole change set
worries about is not narrowly guarded here — it is structurally impossible,
because there is nothing in this table to leak.

WHAT WAS REJECTED, so nobody re-proposes it
-------------------------------------------

- A ``SECURITY DEFINER`` function over ``user_credentials``. Its owner is
  whatever ``DIRECT_URL`` logs in as during ``db-migrate``, which is BYPASSRLS
  — the body would run as a role RLS does not apply to at all. It also ships
  three defaults that fail open: an unpinned ``search_path`` (schema shadowing
  needs no privilege, and this estate has already had one real pooler
  search_path incident), ``EXECUTE`` granted to ``PUBLIC``, and a return type
  that is the only thing stopping the body being widened to return a token
  later.
- A ``BYPASSRLS`` cron role. Turns "leak one tenant" into "leak every refresh
  token".
- A privileged direct-host read. IPv6-only from Vercel, and a second standing
  credential.

THE POLICY, AND EXACTLY WHAT IT EXPOSES
---------------------------------------

``scripts/verify_rls.py`` runs on every production migration and fails unless
every base table in ``public`` except ``alembic_version`` has RLS ENABLEd and
FORCEd and carries at least one policy. So this table gets RLS — and the
SELECT policy must be satisfiable by a connection with **no identity bound**,
or the original problem is simply rebuilt one table to the left.

    CREATE POLICY gmail_sync_enrollment_enumerate ON gmail_sync_enrollment
        FOR SELECT TO jobtracker_app USING (true);

Said plainly, because it should not be discovered later in a comment nobody
reads: **any reader connecting as ``jobtracker_app`` can learn which user_ids
have linked Gmail, and when.** That is the deliberate trade. It is a membership
fact — never a token, never an email address, and it names no row of any other
table. ``TO jobtracker_app`` is not decoration: it means a future grant of
SELECT to some other role still default-denies rather than inheriting this.

Writes stay owner-scoped (``user_id = (SELECT auth.uid())``), so the runtime
role can still only enroll or un-enroll ITSELF. There is no UPDATE policy and
no UPDATE grant: enrollment is membership, and the only two operations on it
are join and leave.

THE BACKFILL IS NOT OPTIONAL
----------------------------

``upgrade()`` populates the table from ``user_credentials``. This revision runs
under ``DIRECT_URL``, the one identity legitimately able to read across
tenants, so it is the only place the existing enrollment set can be recovered.
A green migration over an empty table would leave the cron syncing nobody —
the original bug wearing a new mask.

Backfilled rows carry the migration's timestamp in ``enrolled_at``, not the
original link time. Nothing reads that column yet; membership is what matters.

Membership is deliberately "has a ``gmail_oauth`` row", NOT "has a live one".
``revoked_at`` is not consulted, because ``save_gmail_credentials`` does not
consult it either — defining membership differently here than the dual-write
maintains it is how the two sets drift. A revoked user enrolls and is skipped
by the per-user probe, exactly as a revoked user in today's env allowlist is.

THE ROLE GUARD
--------------

``CREATE POLICY ... TO jobtracker_app`` requires the role to exist. It does in
production (``verify_rls.py`` fails the deploy otherwise), but the chain is
also applied to bare throwaway Postgres containers by
``tests/test_migrations_postgres.py``, ``tests/test_cascade_delete_postgres.py``
and ``scripts/check_expand_only.py``, where it does not.

The guard creates a ``NOLOGIN NOBYPASSRLS`` stub in that case rather than
branching the POLICY shape. Branching the shape would mean the form that ships
to production is the one form no test ever applies, which is the
"check that cannot fail" defect this repo keeps finding. In production the
branch is dead — the role is already there — and every one of those test
runners connects as a superuser, so the stub is creatable. ``NOLOGIN`` means
the stub can never be connected as.

THE GRANT IS THE HIGHEST-RISK LINE HERE
---------------------------------------

No revision has created a table since the cutover to ``jobtracker_app``, so
there is no precedent and no evidence of ``ALTER DEFAULT PRIVILEGES``. A table
the runtime role has no privilege on makes ``save_gmail_credentials`` raise,
which the helper turns into ``False``, which fails the OAuth callback — Gmail
linking would break for every user, not just the cron. Hence an explicit
``GRANT SELECT, INSERT, DELETE``. No UPDATE: nothing updates this table, and
withholding it is free.

DEPLOY
------

Additive under ``scripts/check_expand_only.py``: a new table, no column
removed, no type changed, no NOT NULL added to anything already deployed. One
PR — but note the migrate-vs-deploy race, which is REAL here and is not
engineered around on purpose. ``db-migrate`` and Vercel start together and
nothing orders them; if the code lands first, the enrollment INSERT hits
``UndefinedTable``, aborts the transaction and rolls the credential upsert back
with it, so linking Gmail fails for the minute or two until the migration
finishes. A ``try/except`` around the enrollment write would hide that at the
cost of reintroducing exactly the drift the same-transaction design exists to
prevent. The window is bounded and the user can retry; the drift would be
permanent and silent.

SQLite (desktop, and most of the test suite) creates the table and skips
everything else: no ``auth`` schema, no RLS, no roles, and no rows to backfill.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e2b6f0a4d517"
down_revision: Union[str, Sequence[str], None] = "a9d3e5f2c841"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The role the API connects as, and the only role the enumeration policy names.
RUNTIME_ROLE = "jobtracker_app"


_POSTGRES_UPGRADE_SQL = f"""
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{RUNTIME_ROLE}') THEN
        -- Test containers only; see "THE ROLE GUARD" in the docstring. NOLOGIN
        -- so the stub can never be connected as.
        CREATE ROLE {RUNTIME_ROLE} NOLOGIN NOBYPASSRLS;
    END IF;
END $$;

ALTER TABLE gmail_sync_enrollment
    ADD CONSTRAINT fk_gmail_sync_enrollment_user_id
    FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;

ALTER TABLE gmail_sync_enrollment ENABLE ROW LEVEL SECURITY;
ALTER TABLE gmail_sync_enrollment FORCE ROW LEVEL SECURITY;

-- THE ENUMERATION POLICY. Permissive by design and scoped to one role: the
-- cron binds no identity, so a predicate on auth.uid() would match nothing and
-- rebuild the bug this revision closes. What it exposes to a jobtracker_app
-- connection is WHICH user_ids have linked Gmail and when — a membership fact,
-- never a token and never an address.
CREATE POLICY gmail_sync_enrollment_enumerate ON gmail_sync_enrollment
    FOR SELECT TO {RUNTIME_ROLE} USING (true);

-- Writes stay owner-scoped: the runtime role may enroll or un-enroll ITSELF and
-- nobody else. `(SELECT auth.uid())` rather than a bare call for the InitPlan
-- hoist c6_rls_initplan_hoist put every other policy in.
CREATE POLICY gmail_sync_enrollment_owner_insert ON gmail_sync_enrollment
    FOR INSERT TO {RUNTIME_ROLE}
    WITH CHECK (user_id = (SELECT auth.uid()));

CREATE POLICY gmail_sync_enrollment_owner_delete ON gmail_sync_enrollment
    FOR DELETE TO {RUNTIME_ROLE}
    USING (user_id = (SELECT auth.uid()));

-- No ALTER DEFAULT PRIVILEGES is known to exist for this role, and a table it
-- cannot write breaks the OAuth callback, not just the cron. No UPDATE.
GRANT SELECT, INSERT, DELETE ON gmail_sync_enrollment TO {RUNTIME_ROLE};

-- THE BACKFILL. Runs as DIRECT_URL (BYPASSRLS), the one identity able to read
-- across tenants, and the only moment the existing enrollment set can be
-- recovered. Without it a green migration leaves the cron syncing nobody.
INSERT INTO gmail_sync_enrollment (user_id, enrolled_at)
SELECT user_id, now() FROM user_credentials WHERE kind = 'gmail_oauth'
ON CONFLICT (user_id) DO NOTHING;
"""


_POSTGRES_DOWNGRADE_SQL = f"""
DROP POLICY IF EXISTS gmail_sync_enrollment_owner_delete ON gmail_sync_enrollment;
DROP POLICY IF EXISTS gmail_sync_enrollment_owner_insert ON gmail_sync_enrollment;
DROP POLICY IF EXISTS gmail_sync_enrollment_enumerate ON gmail_sync_enrollment;
REVOKE ALL ON gmail_sync_enrollment FROM {RUNTIME_ROLE};
ALTER TABLE gmail_sync_enrollment DISABLE ROW LEVEL SECURITY;
ALTER TABLE gmail_sync_enrollment
    DROP CONSTRAINT IF EXISTS fk_gmail_sync_enrollment_user_id;
"""


def _is_postgres() -> bool:
    return op.get_context().dialect.name == "postgresql"


def upgrade() -> None:
    """Create the table everywhere; secure and backfill it on Postgres."""

    op.create_table(
        "gmail_sync_enrollment",
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "enrolled_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("user_id"),
    )
    if not _is_postgres():
        # SQLite: no auth schema, no RLS, no roles, and no cloud rows to
        # backfill. The table itself is all there is to create.
        return
    op.execute(_POSTGRES_UPGRADE_SQL)


def downgrade() -> None:
    """Drop the table. The membership fact is recoverable from user_credentials.

    Destructive in the letter of ``scripts/check_expand_only.py`` — a table
    disappears — but nothing is lost that ``upgrade()``'s own backfill query
    cannot rebuild, and no deployed reader exists yet (issue #291 ships the
    reader in a follow-up).
    """

    if _is_postgres():
        op.execute(_POSTGRES_DOWNGRADE_SQL)
    op.drop_table("gmail_sync_enrollment")
