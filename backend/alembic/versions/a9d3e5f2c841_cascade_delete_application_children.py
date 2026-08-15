"""ON DELETE CASCADE for the four application/email child keys

Revision ID: a9d3e5f2c841
Revises: f4c2a8e17b95
Create Date: 2026-08-14 13:30:00.000000

Turns four ``NO ACTION`` foreign keys into ``ON DELETE CASCADE``:

    contacts.application_id         -> applications.id
    emails.application_id           -> applications.id
    interviews.application_id       -> applications.id
    email_embeddings.email_id       -> emails.id

Why
---

``DELETE /account`` (``cloud/account.py``) and ``DELETE /applications/{id}``
both purge children in application code, children-before-parents, precisely
because these keys are NO ACTION and a parent-first delete would be refused.
That works — when it completes. What it does not survive is a PARTIAL failure:
a serverless function killed on its 60 s ceiling, or a connection dropped, part
way through the ordered sequence leaves child rows whose parent is gone.

Those orphans are then unreachable. RLS is FORCEd on every one of these tables
on ``user_id = auth.uid()``, and the deleting user's auth identity is removed by
the web layer immediately after ``DELETE /account`` returns — so nothing can
ever select those rows again, while they keep counting against the 500 MB free
tier. "Deleted my account and it still costs storage nobody can see" is not a
state to ship into a user invite.

CASCADE makes the database enforce the ordering the application already
intends, so the parent delete cannot leave children behind no matter where it
is interrupted.

WHAT THIS DOES NOT DO — and deliberately
-----------------------------------------

No foreign key to ``auth.users`` is added. ``user_credentials`` already has
one (``fk_user_credentials_user_id``, added by ``c4_user_credentials_rls``);
extending that pattern to the seven entity tables couples the whole schema to
the auth schema's lifecycle and is a bigger decision than this change.

The explicit application-level ordering in ``account.py`` and
``delete_application`` STAYS. It is not made redundant: the child deletes are
scoped by ``user_id`` as well, which is a second layer RLS-style, and removing
them would make the purge depend entirely on DDL that this repo has already
discovered can be absent in production. ``account.py``'s comment about
"(RESTRICT-default) foreign keys" is corrected in the same commit — the
ordering is now belt-and-braces rather than a requirement.

Nothing relies on the RESTRICT behaviour to PREVENT a delete: verified by
reading both delete paths and ``tests/test_application_delete_children.py``,
which asserts the children go away, never that a parent delete is refused.

Constraint names
----------------

Read from a real Postgres built by ``alembic upgrade head`` rather than
guessed — ``pg_constraint`` gives ``contacts_application_id_fkey`` and friends,
Postgres's default ``<table>_<column>_fkey``. A guessed name would fail at
apply time against production, which is the worst place to learn one.

Deploy
------

Postgres only. SQLite cannot ALTER a constraint at all (it would need a full
table rebuild), and it does not enforce foreign keys unless a per-connection
pragma is set — so there is nothing here for it to do and a batch_alter_table
recreate would rewrite four tables in the test harness to no purpose.

Under ``scripts/check_expand_only.py`` this is "relaxing a constraint", which
that gate names explicitly as NOT destructive: no column, table or enum label
changes. One PR. Old code is unaffected — it deletes children first regardless,
and a cascade that finds nothing left to cascade is a no-op.

``ALTER TABLE ... DROP CONSTRAINT ... ADD CONSTRAINT`` takes an ACCESS
EXCLUSIVE lock and re-validates the key. On this data (65 applications, a few
hundred emails) that is milliseconds; on a large table it would want
``NOT VALID`` plus a separate ``VALIDATE CONSTRAINT``.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a9d3e5f2c841"
down_revision: Union[str, Sequence[str], None] = "f4c2a8e17b95"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (table, constraint, column, referred table)
_KEYS = (
    ("contacts", "contacts_application_id_fkey", "application_id", "applications"),
    ("emails", "emails_application_id_fkey", "application_id", "applications"),
    ("interviews", "interviews_application_id_fkey", "application_id", "applications"),
    ("email_embeddings", "email_embeddings_email_id_fkey", "email_id", "emails"),
)


def _is_postgres() -> bool:
    return op.get_context().dialect.name == "postgresql"


def _rebuild(ondelete: str | None) -> None:
    for table, name, column, referred in _KEYS:
        op.drop_constraint(name, table, type_="foreignkey")
        op.create_foreign_key(
            name, table, referred, [column], ["id"], ondelete=ondelete
        )


def upgrade() -> None:
    """Re-declare the four keys with ON DELETE CASCADE."""

    if not _is_postgres():
        return
    _rebuild("CASCADE")


def downgrade() -> None:
    """Back to NO ACTION.

    Safe in itself — it only makes the database stricter again — but it
    restores the orphan window the upgrade closed.
    """

    if not _is_postgres():
        return
    _rebuild(None)
