"""an index the company lookup can actually use (lower(company))

Revision ID: e7a1c4d92b30
Revises: a1c7f2e58b04
Create Date: 2026-08-14 12:00:00.000000

Adds ``ix_applications_user_id_lower_company`` — a FUNCTIONAL index on
``(user_id, lower(company))`` with the ``text_pattern_ops`` operator class —
so ``_company_rows`` stops seq-scanning ``applications`` on every call.

Why
---

``cloud/applications.py::_company_rows`` issues two predicates:

    lower(company) =    :token
    lower(company) LIKE :prefix || '%'

Production's only company index is ``ix_applications_company``, on the **raw**
column. A btree on ``company`` cannot answer a question about ``lower(company)``
— the index stores the original bytes and the planner has no way to know the
expression is order-preserving (it is not). So both predicates fall through to a
sequential scan, and ``_company_rows`` is called from inside the per-application
upsert loop, once per rolled cluster.

Why ``text_pattern_ops`` and not the default operator class
-----------------------------------------------------------

This is the part that would have shipped wrong. Supabase's databases are
``en_US.utf8``, and under any non-C collation a **default** btree cannot serve
``LIKE 'prefix%'`` — the collation's sort order is not the byte order the prefix
range would need. Measured on ``postgres:16`` at ``en_US.utf8`` with 300,000
seeded rows:

- default opclass, equality → ``Index Scan``, both columns in ``Index Cond``. ✔
- default opclass, prefix   → ``Bitmap Index Scan`` on ``user_id`` ONLY; the
  ``lower(company) ~~ 'company%'`` clause is left in ``Filter``. The index is
  touched but the prefix is not an index condition — every row of that user is
  read and re-checked.
- ``text_pattern_ops``, prefix → ``Index Cond`` gains
  ``lower(company) ~>=~ 'company' AND lower(company) ~<~ 'companz'``: a real
  range scan. ✔
- ``text_pattern_ops``, equality → still an ``Index Scan`` with both columns in
  ``Index Cond``. ✔

So ONE index in the pattern opclass serves both predicates, and the default
opclass serves only one of them. That is why there is a single index here rather
than the obvious pair — the pair would cost a second write amplification and a
second index's storage against the 500 MB free tier to buy nothing.

Note ``lower()`` is declared IMMUTABLE only for a single-argument call, which is
what this is; the two-argument collation-aware form could not be indexed.

What this does NOT claim
------------------------

No production speed-up is measured or asserted. ``applications`` holds 65 live
rows in the owner's database — far below the point where any planner would
prefer an index to a scan, and a "benchmark" there would be noise dressed as
evidence. What is verified is the thing that actually matters before real users
arrive: that the planner **can** use this index for both predicates once a table
is large enough to want one. That verification is a seeded 300k-row table, not
production.

Deploy
------

Additive, and index-only: no column changes meaning, no data is rewritten, and
old code simply never uses it. One-PR under docs/MIGRATIONS.md — whichever of
the migration workflow and the Vercel deploy wins the race, both halves work.

Postgres only. SQLite has no ``text_pattern_ops`` and the test suite's
``alembic check`` drift test runs on SQLite, so guarding the dialect keeps the
metadata and the chain in agreement there rather than inventing a second index
definition that only one engine could build.

``CONCURRENTLY`` is deliberately NOT used: it cannot run inside a transaction
and ``alembic/env.py`` wraps the whole chain in one, and at 65 rows the table
lock is measured in microseconds. A future large table would need the split.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7a1c4d92b30"
# Re-parented onto a1c7f2e58b04 (#299) during rebase: that revision landed on
# main claiming the same d3f5b81c6a72 parent this one did, and two revisions
# sharing a parent is two heads — which `alembic upgrade head` refuses and
# tests/test_schema_version.py fails on.
down_revision: Union[str, Sequence[str], None] = "a1c7f2e58b04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX_NAME = "ix_applications_user_id_lower_company"


def _is_postgres() -> bool:
    return op.get_context().dialect.name == "postgresql"


def upgrade() -> None:
    """Create the functional index (Postgres only)."""

    if not _is_postgres():
        return
    op.execute(
        f"CREATE INDEX IF NOT EXISTS {INDEX_NAME} "
        "ON applications (user_id, lower(company) text_pattern_ops)"
    )


def downgrade() -> None:
    """Drop it. Losing an index costs speed, never data."""

    if not _is_postgres():
        return
    op.execute(f"DROP INDEX IF EXISTS {INDEX_NAME}")
