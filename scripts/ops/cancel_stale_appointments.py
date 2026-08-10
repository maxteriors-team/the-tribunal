"""Inspect and cancel appointments for one contact against a live database.

Written for the incident where an SMS agent told a customer her appointment was
cancelled but had no tool to actually cancel it: the row stayed ``scheduled``
and the reminder worker kept texting her. The code fix stops it recurring; this
script cleans up the contacts already stuck in that state.

Runs through the app's models, so encrypted columns decrypt correctly (raw SQL
cannot match on ``phone_number``) and the cancellation goes through the same
``cancel_upcoming_appointments`` path the agent now uses — same status, notes,
and tag as an organic cancellation.

Read-only by default. Pass ``--apply`` to write.

Usage:
    railway variables --service Postgres --kv | grep DATABASE_PUBLIC_URL   # host
    railway run --service the-tribunal-api -- env DATABASE_URL="<public+asyncpg url>" \
        uv run python scripts/ops/cancel_stale_appointments.py --phone '+12485551234'
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import selectinload  # noqa: E402

from app.core.encryption import hash_phone  # noqa: E402
from app.db.session import AsyncSessionLocal  # noqa: E402
from app.models.appointment import Appointment, AppointmentStatus  # noqa: E402
from app.models.contact import Contact  # noqa: E402
from app.services.appointments.cancellation import cancel_upcoming_appointments  # noqa: E402


def _mask_phone(phone: str | None) -> str:
    """Show only the last 4 digits — enough to confirm the right person."""
    if not phone:
        return "(none)"
    digits = "".join(ch for ch in phone if ch.isdigit())
    return f"***{digits[-4:]}" if len(digits) >= 4 else "***"


def _mask_email(email: str | None) -> str:
    if not email or "@" not in email:
        return "(none)"
    local, _, domain = email.partition("@")
    return f"{local[:2]}***@{domain}"


async def _find_contacts(db, phone: str | None, email: str | None) -> list[Contact]:
    """Locate the contact by phone hash (indexed) or by decrypting emails.

    ``phone_hash`` exists precisely so an encrypted phone stays searchable;
    email has no such hash, so that path scans and compares in Python.
    """
    if phone:
        result = await db.execute(select(Contact).where(Contact.phone_hash == hash_phone(phone)))
        return list(result.scalars().all())

    result = await db.execute(select(Contact))
    wanted = (email or "").strip().lower()
    return [c for c in result.scalars().all() if (c.email or "").strip().lower() == wanted]


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    identity = parser.add_mutually_exclusive_group(required=True)
    identity.add_argument("--phone", help="E.164 phone, e.g. +12485551234")
    identity.add_argument("--email", help="Contact email")
    parser.add_argument(
        "--reason",
        default="customer cancelled by SMS",
        help="Reason recorded on the appointment notes",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually cancel. Without this the script only reports.",
    )
    args = parser.parse_args()

    db_url = os.environ.get("DATABASE_URL", "")
    if "railway.internal" in db_url:
        print("✗ DATABASE_URL points at *.railway.internal, which is unreachable from here.")
        print("  Override it with the Postgres service's DATABASE_PUBLIC_URL.")
        return 2

    async with AsyncSessionLocal() as db:
        contacts = await _find_contacts(db, args.phone, args.email)

        if not contacts:
            print("✗ no contact matched")
            return 1
        if len(contacts) > 1:
            print(f"⚠ {len(contacts)} contacts matched — refusing to guess:")
            for c in contacts:
                print(f"    id={c.id} ws={c.workspace_id} {_mask_phone(c.phone_number)}")
            return 1

        contact = contacts[0]
        print(
            f"▶ contact id={contact.id} ws={contact.workspace_id} "
            f"name={contact.full_name!r} phone={_mask_phone(contact.phone_number)} "
            f"email={_mask_email(contact.email)}"
        )

        result = await db.execute(
            select(Appointment)
            .where(Appointment.contact_id == contact.id)
            .options(selectinload(Appointment.agent))
            .order_by(Appointment.scheduled_at)
        )
        appointments = list(result.scalars().all())

        now = datetime.now(UTC)
        print(f"\n  {len(appointments)} appointment(s) total:")
        for appt in appointments:
            future = appt.scheduled_at > now
            marker = "→" if (future and appt.status == AppointmentStatus.SCHEDULED) else " "
            print(
                f"  {marker} id={appt.id} {appt.scheduled_at.isoformat()} "
                f"status={appt.status.value} reminders_sent={appt.reminders_sent} "
                f"created={appt.created_at.isoformat()}"
            )

        targets = [
            a
            for a in appointments
            if a.status == AppointmentStatus.SCHEDULED and a.scheduled_at > now
        ]
        print(f"\n  {len(targets)} upcoming scheduled appointment(s) would be cancelled (→).")

        if not targets:
            print("\n✓ nothing to cancel")
            return 0

        if not args.apply:
            print("\n  DRY RUN — re-run with --apply to cancel.")
            return 0

        outcome = await cancel_upcoming_appointments(
            db,
            workspace_id=contact.workspace_id,
            contact_id=contact.id,
            reason=args.reason,
            cancelled_by="operator (incident cleanup)",
        )
        print(f"\n✓ cancelled {outcome.count} appointment(s):")
        for item in outcome.cancelled:
            print(f"    id={item.appointment_id} {item.local_label}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
