"""Seed a local workspace with enough data to make every sales KPI readable.

The point of this script is the *populated* state. Production has 4
appointments and 11 quotes, so every headline KPI legitimately renders a dash or
a low-sample warning there — which is correct behaviour, but it means nobody has
ever seen the report with real numbers in it.

Run against a local database only::

    cd backend && uv run python ../scripts/dev/seed_sales_kpi_demo.py

Prints the workspace id, the login email, and the password so the seeded state
can be opened in the browser.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.core.encryption import hash_phone, hash_value  # noqa: E402
from app.core.security import get_password_hash  # noqa: E402
from app.db.session import AsyncSessionLocal  # noqa: E402
from app.models.appointment import Appointment, AppointmentStatus  # noqa: E402
from app.models.contact import Contact  # noqa: E402
from app.models.opportunity import Opportunity  # noqa: E402
from app.models.quote import Quote  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.workspace import Workspace, WorkspaceMembership  # noqa: E402
from app.services.opportunities.default_pipeline import (  # noqa: E402
    ensure_default_pipeline,
)

PASSWORD = "kpi-demo-password-123"
SUFFIX = uuid.uuid4().hex[:6]


async def main() -> None:
    async with AsyncSessionLocal() as db:
        workspace = Workspace(
            id=uuid.uuid4(),
            name=f"KPI Demo {SUFFIX}",
            slug=f"kpi-demo-{SUFFIX}",
        )
        db.add(workspace)

        email = f"kpi-{SUFFIX}@example.com"
        user = User(
            email=email,
            email_hash=hash_value(email),
            hashed_password=get_password_hash(PASSWORD),
            full_name="Dana Reyes",
            is_active=True,
        )
        db.add(user)
        await db.flush()

        db.add(
            WorkspaceMembership(
                workspace_id=workspace.id, user_id=user.id, role="owner"
            )
        )
        pipeline = await ensure_default_pipeline(db, workspace.id)

        now = datetime.now(UTC)
        window_day = now.replace(day=min(now.day, 15), hour=12, minute=0, microsecond=0)

        # 24 contacts created this month; 7 of them reached a won deal, so
        # conversion reads ~29% off a denominator well past the low-sample line.
        contacts: list[Contact] = []
        for index in range(24):
            phone = f"+1512{4000000 + index + int(SUFFIX, 16) % 1000:07d}"
            contact = Contact(
                workspace_id=workspace.id,
                first_name=f"Lead{index:02d}",
                last_name="Homeowner",
                phone_number=phone,
                phone_hash=hash_phone(phone),
                created_at=window_day - timedelta(days=index % 10),
            )
            db.add(contact)
            contacts.append(contact)
        await db.flush()

        for contact in contacts[:7]:
            db.add(
                Opportunity(
                    workspace_id=workspace.id,
                    pipeline_id=pipeline.id,
                    primary_contact_id=contact.id,
                    name=f"{contact.first_name} — won",
                    status="won",
                )
            )

        # 18 appointments: 13 attended, 5 missed → a 72% show-up rate.
        for index in range(18):
            db.add(
                Appointment(
                    workspace_id=workspace.id,
                    contact_id=contacts[index % len(contacts)].id,
                    scheduled_at=window_day - timedelta(days=index % 12, hours=index),
                    status=(
                        AppointmentStatus.NO_SHOW
                        if index % 4 == 3 and index < 18
                        else AppointmentStatus.COMPLETED
                    ),
                )
            )

        # 20 quotes: 8 approved, 4 declined, 3 expired, 5 still out.
        plan = (
            [("approved", 4_200.0)] * 8
            + [("declined", 3_100.0)] * 4
            + [("expired", 2_800.0)] * 3
            + [("sent", 5_600.0)] * 5
        )
        for index, (status, total) in enumerate(plan):
            db.add(
                Quote(
                    workspace_id=workspace.id,
                    contact_id=contacts[index % len(contacts)].id,
                    number=f"QUO-{SUFFIX}-{index:03d}",
                    subtotal=total,
                    total=total + index * 25,
                    currency="USD",
                    status=status,
                    primary_service="pressure_washing" if index % 2 else "gutters",
                    attach_count=1 if index % 3 == 0 else 0,
                    attach_value=450.0 if index % 3 == 0 else 0.0,
                    created_at=window_day - timedelta(days=index % 14),
                    created_by_id=user.id,
                )
            )

        await db.commit()

    print(f"workspace_id={workspace.id}")
    print(f"email={email}")
    print(f"password={PASSWORD}")


if __name__ == "__main__":
    asyncio.run(main())
