"""Read-only audit for appointments that will text customers they shouldn't.

Two populations, both produced by the same incident class:

1. **Duplicate scheduled rows** — the same contact booked twice into the same
   slot, so every reminder goes out twice. The app-level dedupe guard in
   ``finalize_booking`` stops new ones; this finds rows created before it.
2. **Scheduled-but-cancelled-in-conversation** — the agent said it cancelled but
   had no tool to do so, leaving a live row still queued for reminders.

Never writes. Feed the phones/emails it prints to ``cancel_stale_appointments.py``.

Usage:
    railway run --service the-tribunal-api -- env DATABASE_URL="<public+asyncpg url>" \
        uv run python scripts/ops/audit_stale_appointments.py
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from sqlalchemy import func, select  # noqa: E402

from app.db.session import AsyncSessionLocal  # noqa: E402
from app.models.appointment import Appointment, AppointmentStatus  # noqa: E402
from app.models.contact import Contact  # noqa: E402
from app.models.conversation import Conversation, Message, MessageDirection  # noqa: E402

# Deliberately narrow. A customer writing "cancel" or "I need to cancel" is
# unambiguous; "cancellation policy" or "can I cancel later" is not, and a false
# positive here silently deletes a real appointment.
CANCEL_INTENT = re.compile(
    r"^\s*(cancel"
    r"|cancel it|cancel that|please cancel"
    r"|cancel my (appointment|call|meeting))"
    r"\s*[.!]?\s*$",
    re.IGNORECASE,
)


def _fingerprint(value: str | None) -> str:
    """A short, stable, non-reversible tag for a PII value.

    An audit runs across every workspace, so its output is the last place
    customer emails should land — terminal scrollback and CI logs outlive the
    incident. The digest is enough to tell contacts apart and to correlate a
    row with ``cancel_stale_appointments.py``, and useless to a later reader.
    """
    if not value:
        return "(none)"
    return hashlib.sha256(value.strip().lower().encode()).hexdigest()[:8]


async def _duplicate_slots(db) -> list[tuple[int, datetime, int]]:
    """Contacts holding more than one live booking on the same slot."""
    now = datetime.now(UTC)
    result = await db.execute(
        select(
            Appointment.contact_id,
            Appointment.scheduled_at,
            func.count(Appointment.id).label("n"),
        )
        .where(
            Appointment.status == AppointmentStatus.SCHEDULED,
            Appointment.scheduled_at > now,
        )
        .group_by(Appointment.contact_id, Appointment.scheduled_at)
        .having(func.count(Appointment.id) > 1)
        .order_by(Appointment.scheduled_at)
    )
    return [(row[0], row[1], row[2]) for row in result.all()]


async def _cancelled_in_conversation(db, lookback_days: int) -> list[tuple[int, int, str]]:
    """Live appointments whose contact plainly asked to cancel over SMS."""
    now = datetime.now(UTC)
    result = await db.execute(
        select(Appointment).where(
            Appointment.status == AppointmentStatus.SCHEDULED,
            Appointment.scheduled_at > now,
        )
    )
    appointments = list(result.scalars().all())

    hits: list[tuple[int, int, str]] = []
    for appt in appointments:
        convo_rows = await db.execute(
            select(Conversation.id).where(Conversation.contact_id == appt.contact_id)
        )
        convo_ids = list(convo_rows.scalars().all())
        if not convo_ids:
            continue

        # ``body`` is an EncryptedString: it cannot be filtered in SQL, so the
        # rows come back and the ORM decrypts them for matching here.
        msg_rows = await db.execute(
            select(Message)
            .where(
                Message.conversation_id.in_(convo_ids),
                Message.direction == MessageDirection.INBOUND,
                Message.created_at >= appt.created_at,
            )
            .order_by(Message.created_at.desc())
            .limit(40)
        )
        for message in msg_rows.scalars().all():
            if message.body and CANCEL_INTENT.match(message.body.strip()):
                hits.append((appt.id, appt.contact_id, message.created_at.isoformat()))
                break

    return hits


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lookback-days", type=int, default=90)
    args = parser.parse_args()

    if "railway.internal" in os.environ.get("DATABASE_URL", ""):
        print("✗ DATABASE_URL points at *.railway.internal — use DATABASE_PUBLIC_URL.")
        return 2

    async with AsyncSessionLocal() as db:
        print("── duplicate live bookings on one slot ──")
        dupes = await _duplicate_slots(db)
        if not dupes:
            print("  none")
        for contact_id, slot, count in dupes:
            contact = await db.get(Contact, contact_id)
            label = _fingerprint(contact.email) if contact else "?"
            print(f"  contact={contact_id} fp={label} slot={slot.isoformat()} rows={count}")

        print("\n── live bookings the customer asked to cancel ──")
        stale = await _cancelled_in_conversation(db, args.lookback_days)
        if not stale:
            print("  none")
        for appt_id, contact_id, when in stale:
            contact = await db.get(Contact, contact_id)
            label = _fingerprint(contact.email) if contact else "?"
            print(f"  appointment={appt_id} contact={contact_id} fp={label} asked_at={when}")

        print(f"\n{len(dupes)} duplicate slot(s), {len(stale)} ignored cancellation(s).")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
