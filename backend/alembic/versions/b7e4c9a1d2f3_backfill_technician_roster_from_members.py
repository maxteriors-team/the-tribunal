"""put existing field-role members on the dispatch roster

Jobs are tagged to a ``technicians`` row, but membership writes only ever
created a ``workspace_memberships`` row. Every workspace that hired a technician
the way the product offers — invite, or bulk-provision, with the ``technician``
/ ``lead_technician`` role — therefore has field staff who cannot be assigned to
any job: the "tag workers" list is empty.

:mod:`app.services.field_service.roster` fixes that going forward. This
migration repairs the workspaces that already hired, in three steps:

1. Unlink duplicate roster rows for the same login (keeping the earliest), so
   the new invariant can be enforced. Unlinking, not deleting, keeps the job
   assignment history on the duplicate.
2. Create the partial unique index that makes "one login, one roster row per
   workspace" a database rule, which is what keeps the runtime provisioning
   idempotent under concurrent membership writes.
3. Backfill a roster row for every field-role member that lacks one, claiming an
   unlinked row with the same email (e.g. a crew imported from Jobber before the
   hire got a login) instead of listing that person on the board twice.

``users.email`` is Fernet-encrypted at rest, so the backfill decrypts through
the app's ``EncryptedString`` type rather than reading the column as text; the
roster stores staff contact details in plain text, mirroring ``bookable_staff``.

Downgrade drops the index only. Deleting backfilled roster rows would take live
job assignments with them, and an extra dispatchable name is not a schema
problem — the rows are indistinguishable from ones an operator typed by hand.

Revision ID: b7e4c9a1d2f3
Revises: c8d1f4a92b76
Create Date: 2026-08-10 00:00:00.000000

"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from cryptography.fernet import InvalidToken

from alembic import op
from app.core.encryption import EncryptedString

revision: str = "b7e4c9a1d2f3"
down_revision: str | Sequence[str] | None = "c8d1f4a92b76"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FIELD_ROLES = ("technician", "lead_technician")
_INDEX_NAME = "uq_technicians_workspace_user"

_NAME_MAX = 200
_EMAIL_MAX = 255
_PHONE_MAX = 50


def _decrypt(bind: sa.Connection, value: str | None) -> str | None:
    """Best-effort decrypt of an ``EncryptedString`` column read as raw text.

    Returns ``None`` when the ciphertext will not open under the configured key
    (a row written before a key rotation, say). That is deliberate: this runs
    inside ``alembic upgrade head``, which is the Railway **pre-deploy** step,
    so raising here turns one unreadable row into a failed release. A roster row
    that is missing its email is a cosmetic gap any operator can fill in from
    the technician editor — losing the deploy is not.
    """
    try:
        return EncryptedString().process_result_value(value, bind.dialect)
    except InvalidToken:
        return None


def _unlink_duplicate_logins(bind: sa.Connection) -> None:
    """Keep the earliest roster row per (workspace, login); unlink the rest."""
    bind.execute(
        sa.text(
            """
            UPDATE technicians
            SET user_id = NULL
            WHERE id IN (
                SELECT id
                FROM (
                    SELECT
                        id,
                        ROW_NUMBER() OVER (
                            PARTITION BY workspace_id, user_id
                            ORDER BY created_at, id
                        ) AS rn
                    FROM technicians
                    WHERE user_id IS NOT NULL
                ) ranked
                WHERE ranked.rn > 1
            )
            """
        )
    )


def _backfill_field_role_members(bind: sa.Connection) -> None:
    members = bind.execute(
        sa.text(
            """
            SELECT
                m.workspace_id AS workspace_id,
                u.id AS user_id,
                u.full_name AS full_name,
                u.email AS email,
                u.phone_number AS phone_number
            FROM workspace_memberships m
            JOIN users u ON u.id = m.user_id
            WHERE m.role = ANY(:roles)
              AND NOT EXISTS (
                  SELECT 1
                  FROM technicians t
                  WHERE t.workspace_id = m.workspace_id
                    AND t.user_id = m.user_id
              )
            ORDER BY m.workspace_id, u.id
            """
        ),
        {"roles": list(_FIELD_ROLES)},
    ).mappings().all()

    now = datetime.now(UTC)
    for member in members:
        email = _decrypt(bind, member["email"])
        phone = _decrypt(bind, member["phone_number"])
        name = (member["full_name"] or "").strip()
        if not name:
            name = (email or "").split("@", 1)[0]
        # Numbered, never a bare "Technician": with nothing readable to go on,
        # two blank hires would otherwise be indistinguishable in the list a
        # dispatcher picks from.
        name = (name or f"Technician #{member['user_id']}")[:_NAME_MAX]

        claimed = None
        if email:
            claimed = bind.execute(
                sa.text(
                    """
                    UPDATE technicians
                    SET user_id = :user_id,
                        is_active = TRUE,
                        updated_at = :now
                    WHERE id = (
                        SELECT id
                        FROM technicians
                        WHERE workspace_id = :workspace_id
                          AND user_id IS NULL
                          AND LOWER(email) = LOWER(:email)
                        ORDER BY created_at, id
                        LIMIT 1
                    )
                    RETURNING id
                    """
                ),
                {
                    "user_id": member["user_id"],
                    "workspace_id": member["workspace_id"],
                    "email": email,
                    "now": now,
                },
            ).first()
        if claimed is not None:
            continue

        bind.execute(
            sa.text(
                """
                INSERT INTO technicians (
                    id, workspace_id, user_id, name, email, phone,
                    skills, is_active, created_at, updated_at
                )
                VALUES (
                    :id, :workspace_id, :user_id, :name, :email, :phone,
                    '{}', TRUE, :now, :now
                )
                """
            ),
            {
                "id": uuid.uuid4(),
                "workspace_id": member["workspace_id"],
                "user_id": member["user_id"],
                "name": name,
                "email": (email or None) and email[:_EMAIL_MAX],
                "phone": (phone or None) and phone[:_PHONE_MAX],
                "now": now,
            },
        )


def upgrade() -> None:
    bind = op.get_bind()
    _unlink_duplicate_logins(bind)
    op.create_index(
        _INDEX_NAME,
        "technicians",
        ["workspace_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )
    _backfill_field_role_members(bind)


def downgrade() -> None:
    op.drop_index(_INDEX_NAME, table_name="technicians")
