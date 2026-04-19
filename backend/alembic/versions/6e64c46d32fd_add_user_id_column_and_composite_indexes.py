"""add user_id column and composite indexes

Revision ID: 6e64c46d32fd
Revises: d7da4461f034
Create Date: 2026-04-18 21:36:00.098297

Adds a ``user_id`` UUID column to every entity table, backfills existing
rows with the local-user sentinel
(``00000000-0000-0000-0000-000000000000``), sets the column ``NOT NULL``,
and creates a per-table composite index on ``(user_id, <existing index
col>)`` so the hot query shape "filter-by-owner-then-by-X" stays cheap on
both SQLite (desktop) and Postgres (cloud).

Design notes
------------

- We use ``sa.Uuid(as_uuid=True)`` which renders as native ``UUID`` on
  Postgres and ``CHAR(32)`` on SQLite, so the migration applies cleanly
  against both dialects without ``op.execute`` branching.
- The column is created nullable first, then we backfill, then we flip
  ``NOT NULL`` inside a ``batch_alter_table`` block. That sequence is
  required on SQLite (``ALTER COLUMN`` is only available via batch copy)
  and equivalent-or-better on Postgres.
- RLS policies live in a separate, Postgres-only migration
  (``6f71e2a9c8b1_enable_rls_policies``). Keeping the column migration
  dialect-agnostic means CI (SQLite) can run ``alembic upgrade head``
  without the Postgres-only SQL blowing up.
- ``sync_state.account_email`` loses its global UNIQUE constraint in
  favour of a composite ``UNIQUE(user_id, account_email)``. Two Supabase
  users connecting the same iCloud account is a legitimate cloud case;
  global uniqueness would block it and there is no downside on desktop
  (single-user).

The follow-up revision `a9b04be1dcee_set_user_id_not_null.py` no longer
exists — we chose to do backfill + NOT NULL in this single revision
because the two steps share the same ``batch_alter_table`` context on
SQLite and the same transaction on Postgres, which keeps the migration
atomic.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6e64c46d32fd'
down_revision: Union[str, Sequence[str], None] = 'd7da4461f034'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Sentinel UUID that matches jobtracker.database.models.LOCAL_USER_ID.
# Kept as a string here so the migration has no runtime import from the
# app package (Alembic sometimes imports the models module before it has
# been fully set up, and we want this migration to run standalone).
LOCAL_USER_ID = "00000000-0000-0000-0000-000000000000"

# (table, existing_index_column) pairs for the composite index step.
# The first element of each composite index is user_id so range queries
# on "rows belonging to this user" can seek directly.
TABLES_WITH_USER_ID: list[tuple[str, str]] = [
    ("applications", "status"),
    ("emails", "received_at"),
    ("contacts", "application_id"),
    ("interviews", "application_id"),
    ("training_data", "label"),
    ("email_embeddings", "label"),
    ("sync_state", "account_email"),
]


def upgrade() -> None:
    """Upgrade schema."""

    bind = op.get_bind()
    dialect_name = bind.dialect.name

    # -------------------------------------------------------------------
    # 1. Add ``user_id`` column (nullable first) to every entity table.
    # -------------------------------------------------------------------
    for table_name, _ in TABLES_WITH_USER_ID:
        with op.batch_alter_table(table_name, schema=None) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "user_id",
                    sa.Uuid(as_uuid=True),
                    nullable=True,
                )
            )

    # -------------------------------------------------------------------
    # 2. Backfill existing rows with the local-user sentinel UUID.
    # -------------------------------------------------------------------
    if dialect_name == "postgresql":
        cast_expr = f"'{LOCAL_USER_ID}'::uuid"
    else:
        # SQLite stores sa.Uuid as CHAR(32) without dashes; SQLAlchemy's
        # UUID type coerces on read, but the raw SQL UPDATE here bypasses
        # type conversion, so we write the dash-less form directly.
        cast_expr = "'00000000000000000000000000000000'"

    for table_name, _ in TABLES_WITH_USER_ID:
        op.execute(
            f"UPDATE {table_name} SET user_id = {cast_expr} WHERE user_id IS NULL"
        )

    # -------------------------------------------------------------------
    # 3. Flip user_id to NOT NULL on every table.
    # -------------------------------------------------------------------
    for table_name, _ in TABLES_WITH_USER_ID:
        with op.batch_alter_table(table_name, schema=None) as batch_op:
            batch_op.alter_column(
                "user_id",
                existing_type=sa.Uuid(as_uuid=True),
                nullable=False,
            )

    # -------------------------------------------------------------------
    # 4. Create the single-column user_id index on every table so the
    #    tenant-scope filter ("WHERE user_id = :uid") never table-scans.
    #    This matches the ``index=True`` declaration in models.py.
    # -------------------------------------------------------------------
    for table_name, _ in TABLES_WITH_USER_ID:
        with op.batch_alter_table(table_name, schema=None) as batch_op:
            batch_op.create_index(
                batch_op.f(f"ix_{table_name}_user_id"),
                ["user_id"],
                unique=False,
            )

    # -------------------------------------------------------------------
    # 5. Composite ``(user_id, <existing>)`` indexes. Complements the
    #    pre-existing single-col index on <existing> so queries that
    #    filter by owner *and* sort/filter by the second column stay
    #    index-only.
    # -------------------------------------------------------------------
    for table_name, second_col in TABLES_WITH_USER_ID:
        with op.batch_alter_table(table_name, schema=None) as batch_op:
            batch_op.create_index(
                f"ix_{table_name}_user_id_{second_col}",
                ["user_id", second_col],
                unique=False,
            )

    # -------------------------------------------------------------------
    # 6. sync_state: drop the global UNIQUE on account_email and add a
    #    composite UNIQUE(user_id, account_email). Two users can now
    #    connect the same iCloud account independently.
    #
    #    The initial migration declared the constraint inline with no
    #    explicit name, so SQLite stores it as unnamed and Postgres
    #    auto-generates ``sync_state_account_email_key``. The strategies
    #    diverge by dialect:
    #
    #    - Postgres: inspect the table, find the single-column UQ on
    #      ``account_email``, drop it by its reflected name, then add
    #      the composite.
    #    - SQLite: ``batch_alter_table`` rebuilds the table by copying
    #      from a Table reflected from the live DB. An unnamed UQ is
    #      preserved through that rebuild unless we pass an explicit
    #      ``copy_from`` Table whose ``__table_args__`` do not include
    #      it. We use the ``naming_convention`` escape hatch: reflect
    #      the table with a convention that auto-names UNIQUE
    #      constraints so ``batch_alter_table`` can then drop them by
    #      that predictable name.
    # -------------------------------------------------------------------
    inspector = sa.inspect(bind)
    existing_uqs = inspector.get_unique_constraints("sync_state")
    old_uq_name: str | None = None
    for uq in existing_uqs:
        if uq.get("column_names") == ["account_email"]:
            old_uq_name = uq.get("name")
            break

    if dialect_name == "sqlite":
        # Reflect sync_state into a fresh Table object whose UNIQUE
        # constraints have deterministic names, then use that as
        # ``copy_from`` so batch_alter_table rebuilds the table
        # *without* the unnamed single-column UNIQUE on account_email.
        naming_convention = {
            "uq": "uq_%(table_name)s_%(column_0_name)s",
        }
        sync_state_md = sa.MetaData(naming_convention=naming_convention)
        sync_state_tbl = sa.Table(
            "sync_state", sync_state_md, autoload_with=bind
        )
        with op.batch_alter_table(
            "sync_state", schema=None, copy_from=sync_state_tbl
        ) as batch_op:
            batch_op.drop_constraint(
                "uq_sync_state_account_email", type_="unique"
            )
            batch_op.create_unique_constraint(
                "uq_sync_state_user_account",
                ["user_id", "account_email"],
            )
    else:
        # Postgres (and any future dialect where reflection returns
        # the constraint name).
        with op.batch_alter_table("sync_state", schema=None) as batch_op:
            if old_uq_name:
                batch_op.drop_constraint(old_uq_name, type_="unique")
            batch_op.create_unique_constraint(
                "uq_sync_state_user_account",
                ["user_id", "account_email"],
            )


def downgrade() -> None:
    """Downgrade schema."""

    bind = op.get_bind()
    dialect_name = bind.dialect.name

    # Reverse step 6.
    with op.batch_alter_table("sync_state", schema=None) as batch_op:
        batch_op.drop_constraint("uq_sync_state_user_account", type_="unique")
        if dialect_name == "postgresql":
            batch_op.create_unique_constraint(
                "sync_state_account_email_key",
                ["account_email"],
            )
        else:
            batch_op.create_unique_constraint(
                "uq_sync_state_account_email",
                ["account_email"],
            )

    # Reverse step 5 (composite indexes).
    for table_name, second_col in TABLES_WITH_USER_ID:
        with op.batch_alter_table(table_name, schema=None) as batch_op:
            batch_op.drop_index(f"ix_{table_name}_user_id_{second_col}")

    # Reverse step 4 (single-col user_id indexes).
    for table_name, _ in TABLES_WITH_USER_ID:
        with op.batch_alter_table(table_name, schema=None) as batch_op:
            batch_op.drop_index(f"ix_{table_name}_user_id")

    # Reverse steps 1-3 (drop the column).
    for table_name, _ in TABLES_WITH_USER_ID:
        with op.batch_alter_table(table_name, schema=None) as batch_op:
            batch_op.drop_column("user_id")
