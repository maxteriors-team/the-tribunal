"""make "one live booking per contact per slot" a database rule

A customer booked a discovery call over SMS and the agent wrote the appointment
twice, 61 seconds apart, because the model called ``book_appointment`` once when
she picked the time and again when she gave her email. She then received every
reminder twice.

``finalize_booking`` already looks for an existing booking before inserting, but
that is a read followed by a write with no lock between them: two tool calls
racing (or two workers, or a retry landing beside the original) both read "no
duplicate" and both insert. The application guard narrows the window; only the
database can close it.

The index is partial on ``status = 'scheduled'`` because the uniqueness only
holds for *live* bookings. A contact may legitimately hold a cancelled row and a
new one on the same slot — that is a rebooking, and a total unique index would
reject it.

Pre-existing duplicates are collapsed first, otherwise the index cannot be
built. The newest row is cancelled and the earliest kept: the earliest is the
one whose confirmation the customer actually received, and its id is the one
referenced by any reminder already sent.

Downgrade drops the index only. Re-splitting collapsed rows is not possible, and
the cancelled duplicates are indistinguishable from ordinary cancellations.

Revision ID: c8d1f4a92b76
Revises: a7f3c21d9e04
Create Date: 2026-08-10 13:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c8d1f4a92b76"
down_revision: str | Sequence[str] | None = "a7f3c21d9e04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX_NAME = "uq_appointments_live_contact_slot"


def _collapse_duplicate_bookings(bind: sa.engine.Connection) -> None:
    """Cancel all but the earliest live booking on each contact+slot.

    Notes record why, so an operator reading the row later sees a deliberate
    cleanup rather than an unexplained cancellation.
    """
    result = bind.execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY workspace_id, contact_id, scheduled_at
                        ORDER BY created_at, id
                    ) AS rn
                FROM appointments
                WHERE status = 'scheduled'
            )
            UPDATE appointments AS a
            SET status = 'cancelled',
                notes = COALESCE(a.notes || E'\\n', '')
                    || '[migration c8d1f4a92b76] Cancelled as a duplicate booking '
                    || 'on the same slot; the earliest booking was kept.',
                updated_at = NOW()
            FROM ranked
            WHERE a.id = ranked.id
              AND ranked.rn > 1
            RETURNING a.id
            """
        )
    )
    collapsed = result.fetchall()
    if collapsed:
        print(f"  collapsed {len(collapsed)} duplicate appointment(s): {[r[0] for r in collapsed]}")


def upgrade() -> None:
    bind = op.get_bind()
    _collapse_duplicate_bookings(bind)
    op.create_index(
        _INDEX_NAME,
        "appointments",
        ["workspace_id", "contact_id", "scheduled_at"],
        unique=True,
        postgresql_where=sa.text("status = 'scheduled'"),
    )


def downgrade() -> None:
    op.drop_index(_INDEX_NAME, table_name="appointments")
