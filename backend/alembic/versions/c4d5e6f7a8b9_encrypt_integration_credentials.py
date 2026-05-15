"""Encrypt integration credentials.

Converts the workspace_integrations.credentials column from JSONB (plaintext)
to TEXT (Fernet-encrypted JSON). Existing plaintext JSONB values are encrypted
in-place during the upgrade.

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-03-24 00:00:00.000000
"""

import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "c4d5e6f7a8b9"
down_revision: str | None = "b3c4d5e6f7a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Step 1: Add a temporary text column for encrypted data
    op.add_column(
        "workspace_integrations",
        sa.Column("credentials_encrypted", sa.Text(), nullable=True),
    )

    # Step 2: Encrypt existing plaintext JSONB credentials into the new column
    # Import here to avoid issues if encryption module isn't available during downgrade
    from app.core.encryption import encrypt_json

    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, credentials FROM workspace_integrations")
    ).fetchall()

    for row in rows:
        row_id, creds = row
        # JSONB comes back as a dict from psycopg/asyncpg
        if isinstance(creds, str):
            creds = json.loads(creds)
        encrypted = encrypt_json(creds)
        conn.execute(
            sa.text(
                "UPDATE workspace_integrations SET credentials_encrypted = :enc WHERE id = :id"
            ),
            {"enc": encrypted, "id": row_id},
        )

    # Step 3: Drop the old JSONB column
    op.drop_column("workspace_integrations", "credentials")

    # Step 4: Rename the encrypted column to 'credentials'
    op.alter_column(
        "workspace_integrations",
        "credentials_encrypted",
        new_column_name="credentials",
        nullable=False,
    )


def downgrade() -> None:
    # Step 1: Add a temporary JSONB column for decrypted data
    op.add_column(
        "workspace_integrations",
        sa.Column("credentials_plaintext", JSONB(), nullable=True),
    )

    # Step 2: Decrypt back to plaintext JSONB
    from app.core.encryption import decrypt_json

    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, credentials FROM workspace_integrations")
    ).fetchall()

    for row in rows:
        row_id, encrypted = row
        decrypted = decrypt_json(encrypted)
        conn.execute(
            sa.text(
                "UPDATE workspace_integrations SET credentials_plaintext = :creds WHERE id = :id"
            ),
            {"creds": json.dumps(decrypted), "id": row_id},
        )

    # Step 3: Drop the encrypted text column
    op.drop_column("workspace_integrations", "credentials")

    # Step 4: Rename back to credentials
    op.alter_column(
        "workspace_integrations",
        "credentials_plaintext",
        new_column_name="credentials",
        nullable=False,
        type_=JSONB(),
    )
