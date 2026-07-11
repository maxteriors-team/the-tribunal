"""Seed a minimal workspace for local inbound-SMS AI-agent verification.

Creates (idempotently): a workspace, an operator user + membership, a Telnyx
phone number that inbound texts are addressed to, a default agent, and a
contact that plays the role of the texting customer. Prints the phone numbers
so a Telnyx webhook replay can target them.

Run: uv run python scripts/dev/seed_inbound_sms_demo.py
"""

import asyncio
import uuid

from sqlalchemy import select

from app.core.encryption import hash_phone, hash_value
from app.core.security import get_password_hash
from app.db.session import AsyncSessionLocal
from app.models.contact import Contact
from app.models.phone_number import PhoneNumber
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership
from app.services.agents.default_agent import ensure_default_agent

WORKSPACE_PHONE = "+15550001111"  # the number the customer texts (our Telnyx DID)
CUSTOMER_PHONE = "+15550002222"  # the customer's number (inbound "from")
OPERATOR_EMAIL = "sms-demo-operator@example.com"


async def _get_or_create_user(db) -> User:
    email_hash = hash_value(OPERATOR_EMAIL)
    existing = await db.execute(select(User).where(User.email_hash == email_hash))
    user = existing.scalar_one_or_none()
    if user is not None:
        return user
    user = User(
        email=OPERATOR_EMAIL,
        email_hash=email_hash,
        hashed_password=get_password_hash("demo-password-123"),
        full_name="SMS Demo Operator",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _get_or_create_workspace(db, user: User) -> Workspace:
    existing = await db.execute(select(Workspace).where(Workspace.name == "Inbound SMS Demo"))
    workspace = existing.scalar_one_or_none()
    if workspace is None:
        workspace = Workspace(name="Inbound SMS Demo", slug="inbound-sms-demo")
        db.add(workspace)
        await db.flush()

    membership_exists = await db.execute(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace.id,
            WorkspaceMembership.user_id == user.id,
        )
    )
    if membership_exists.scalar_one_or_none() is None:
        db.add(WorkspaceMembership(workspace_id=workspace.id, user_id=user.id, role="owner"))
        await db.flush()
    return workspace


async def _get_or_create_phone(db, workspace_id: uuid.UUID, agent_id: uuid.UUID) -> None:
    existing = await db.execute(
        select(PhoneNumber).where(PhoneNumber.phone_number == WORKSPACE_PHONE)
    )
    phone = existing.scalar_one_or_none()
    if phone is None:
        db.add(
            PhoneNumber(
                workspace_id=workspace_id,
                phone_number=WORKSPACE_PHONE,
                friendly_name="Demo DID",
                sms_enabled=True,
                voice_enabled=True,
                is_active=True,
                assigned_agent_id=agent_id,
            )
        )
        await db.flush()


async def _get_or_create_contact(db, workspace_id: uuid.UUID) -> None:
    phone_hash = hash_phone(CUSTOMER_PHONE)
    existing = await db.execute(
        select(Contact).where(
            Contact.workspace_id == workspace_id, Contact.phone_hash == phone_hash
        )
    )
    if existing.scalar_one_or_none() is None:
        db.add(
            Contact(
                workspace_id=workspace_id,
                first_name="Demo",
                last_name="Customer",
                phone_number=CUSTOMER_PHONE,
                phone_hash=phone_hash,
                status="new",
            )
        )
        await db.flush()


async def main() -> None:
    async with AsyncSessionLocal() as db:
        user = await _get_or_create_user(db)
        workspace = await _get_or_create_workspace(db, user)
        agent = await ensure_default_agent(db, workspace.id)
        # Speed up the human-like send delay so a local send hop fires quickly.
        agent.text_response_delay_ms = 1000
        await _get_or_create_phone(db, workspace.id, agent.id)
        await _get_or_create_contact(db, workspace.id)
        await db.commit()

        print("SEED_OK")
        print(f"workspace_id={workspace.id}")
        print(f"agent_id={agent.id}")
        print(f"workspace_phone={WORKSPACE_PHONE}")
        print(f"customer_phone={CUSTOMER_PHONE}")


if __name__ == "__main__":
    asyncio.run(main())
