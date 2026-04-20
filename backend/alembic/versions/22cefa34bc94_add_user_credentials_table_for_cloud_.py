"""add user_credentials table for cloud Fernet storage

Creates the `user_credentials` table used by
``jobtracker.credentials.cloud`` (issue #21, C4). One row per
(user_id, kind) pair; kind is ``gmail_oauth`` or ``icloud_mail``.
The ``ciphertext`` column is an opaque Fernet token; the encryption
key is configured via ``settings.secret_encryption_key``.

A separate migration (filed by this same issue) enables Postgres
Row-Level Security on the table and adds the FK to ``auth.users``
— both are Postgres-only, so they are kept out of this cross-dialect
DDL step.

Revision ID: 22cefa34bc94
Revises: a8d4ec5fba26
Create Date: 2026-04-20 07:48:22.449447

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "22cefa34bc94"
down_revision: Union[str, Sequence[str], None] = "a8d4ec5fba26"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the user_credentials table.

    Columns mirror ``jobtracker.database.models.UserCredential``:

    - user_id: UUID, part of composite PK
    - kind: TEXT, 'gmail_oauth' | 'icloud_mail', part of composite PK
    - ciphertext: BYTEA (Postgres) / BLOB (SQLite) — Fernet-encrypted blob
    - nonce: BYTEA/BLOB — reserved for future AEAD; Fernet embeds its
      own IV so this stays empty for the v1 implementation
    - key_id: TEXT — encryption key identifier (rotation support)
    - created_at / updated_at: TIMESTAMPTZ, server-default NOW()
    """

    op.create_table(
        "user_credentials",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column(
            "key_id",
            sa.Text(),
            server_default="v1",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('gmail_oauth', 'icloud_mail')",
            name="ck_user_credentials_kind",
        ),
        sa.PrimaryKeyConstraint(
            "user_id", "kind", name="pk_user_credentials"
        ),
    )
    with op.batch_alter_table("user_credentials", schema=None) as batch_op:
        batch_op.create_index(
            "ix_user_credentials_kind", ["kind"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("user_credentials", schema=None) as batch_op:
        batch_op.drop_index("ix_user_credentials_kind")

    op.drop_table("user_credentials")
