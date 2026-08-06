"""Seed a local workspace with enough data to make every sales KPI readable.

The point of this script is the *populated* state. Production has 4
appointments and 11 quotes, so every headline KPI legitimately renders a dash or
a low-sample warning there — which is correct behaviour, but it means nobody has
ever seen the report with real numbers in it.

Run against a local database only::

    cd backend && uv run python ../scripts/dev/seed_sales_kpi_demo.py

Prints the workspace id, the login email, and the password so the seeded state
can be opened in the browser.

This refuses to run anywhere but a local database. It creates a *login* -- a
workspace owner whose password is printed to the terminal -- so pointing it at
production would mint a real account with a known credential in a tenant full of
customer data, alongside ~90 rows of fake contacts, quotes and appointments that
would then be indistinguishable from real ones in every KPI it exists to
populate. Both guards below are deliberately fail-closed: an unrecognised host or
an unset ``ENVIRONMENT`` aborts rather than assuming local.
"""

from __future__ import annotations

import asyncio
import os
import secrets
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.core.config import settings  # noqa: E402
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

# The environments this codebase already treats as "not deployed" -- same set as
# ``_validate_public_urls`` in app/main.py and ``Settings.secure_auth_cookies``.
# Kept identical on purpose: two competing definitions of "is this production?"
# is how one of them ends up wrong.
LOCAL_ENVIRONMENTS = {"development", "local", "test", "testing"}

# Allowlist rather than a blocklist of known production hosts. A blocklist is
# only as good as its last update -- it silently fails open the day a database
# moves to a host nobody added to it, which is exactly the day this matters.
LOCAL_DB_HOSTS = {
    "",  # a socket path or hostless URL is inherently local
    "localhost",
    "127.0.0.1",
    "::1",
    "host.docker.internal",
    "postgres",  # docker-compose service name
    "db",
    "aicrm-postgres",  # this repo's compose container
}


class UnsafeTargetError(RuntimeError):
    """The configured target is not a local development database."""


def _resolve_password() -> str:
    """Return the demo password: ``SEED_DEMO_PASSWORD`` or a fresh random one.

    Generated rather than hardcoded so the repository never carries a working
    credential, and so two people seeding demos do not end up sharing one. It is
    printed at the end because the whole point is to log in as this user.
    """
    supplied = os.environ.get("SEED_DEMO_PASSWORD", "").strip()
    if supplied:
        if len(supplied) < 8:
            raise UnsafeTargetError(
                "SEED_DEMO_PASSWORD is shorter than the 8 characters the app "
                "requires; the seeded account would be unusable."
            )
        return supplied
    # token_urlsafe(12) is 16 chars, comfortably past the 8-char minimum.
    return secrets.token_urlsafe(12)


def assert_local_target() -> None:
    """Abort unless both the environment and the database look local.

    Raises:
        UnsafeTargetError: if ``ENVIRONMENT`` is not a local one, or
            ``DATABASE_URL`` points somewhere outside :data:`LOCAL_DB_HOSTS`.
    """
    environment = settings.environment.strip().lower()
    if environment not in LOCAL_ENVIRONMENTS:
        raise UnsafeTargetError(
            f"ENVIRONMENT is {environment!r}, not one of "
            f"{sorted(LOCAL_ENVIRONMENTS)}. This script seeds ~90 fake records "
            "and a known-password owner account; it must never run outside a "
            "local database."
        )

    # Parse rather than substring-match: a password or query parameter can
    # contain any hostname you care to look for, so `"localhost" in url` is not
    # a check, it is a coincidence waiting to happen.
    host = (urlsplit(settings.database_url).hostname or "").lower()
    if host not in LOCAL_DB_HOSTS:
        raise UnsafeTargetError(
            f"DATABASE_URL points at host {host!r}, which is not a recognised "
            f"local host ({sorted(h for h in LOCAL_DB_HOSTS if h)}). Refusing to "
            "seed demo data into a database that may hold real customers. Point "
            "DATABASE_URL at your local Postgres (make dev.db) and re-run."
        )


SUFFIX = uuid.uuid4().hex[:6]


async def main() -> None:
    # Before anything opens a connection.
    assert_local_target()
    password = _resolve_password()

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
            hashed_password=get_password_hash(password),
            full_name="Dana Reyes",
            is_active=True,
        )
        db.add(user)
        await db.flush()

        db.add(WorkspaceMembership(workspace_id=workspace.id, user_id=user.id, role="owner"))
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
    print(f"password={password}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except UnsafeTargetError as exc:
        # Exit non-zero and say why, so a scripted caller fails loudly instead
        # of reporting success over a seed that never happened.
        print(f"refusing to seed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
