"""add email campaign support

Adds email campaigns as a first-class campaign type alongside SMS and voice:

- ``campaigns.email_subject`` (nullable Text) holds the subject line for
  ``campaign_type = 'email'`` campaigns. Supports {first_name}/{company_name}
  placeholders, rendered at send time.
- ``campaigns.from_phone_number`` becomes nullable — email campaigns send via
  Resend and have no phone sender identity. SMS/voice campaigns continue to
  require a sender (enforced at the API layer, not the DB).

The ``campaign_type`` column is a non-native varchar enum (native_enum=False),
so the new 'email' value needs no DB constraint change. Email statistics columns
(emails_sent, emails_delivered, ...) already exist on the table.

Revision ID: e7f8a9b0c1d2
Revises: 7c1e9a4b2f30
Create Date: 2026-07-01
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, None] = "7c1e9a4b2f30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column("email_subject", sa.Text(), nullable=True),
    )
    op.alter_column(
        "campaigns",
        "from_phone_number",
        existing_type=sa.String(length=50),
        nullable=True,
    )


def downgrade() -> None:
    # Restore NOT NULL only if no rows violate it (email campaigns would).
    op.execute(
        "UPDATE campaigns SET from_phone_number = '' WHERE from_phone_number IS NULL"
    )
    op.alter_column(
        "campaigns",
        "from_phone_number",
        existing_type=sa.String(length=50),
        nullable=False,
    )
    op.drop_column("campaigns", "email_subject")
