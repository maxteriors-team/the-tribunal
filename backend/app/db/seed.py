"""Database seeding utilities."""

import asyncio
import os
import sys
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_password_hash
from app.db.session import AsyncSessionLocal
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership
from app.utils.pii import mask_email

# Workspace ID used by frontend. Overridable via env var for non-default deployments;
# falls back to the historical hardcoded UUID so existing setups keep working.
DEFAULT_WORKSPACE_ID = uuid.UUID(
    os.environ.get("DEFAULT_WORKSPACE_ID", "ba0e0e99-c7c9-45ec-9625-567d54d6e9c2")
)

# Default admin credentials from environment (required for seeding)
DEFAULT_ADMIN_EMAIL = os.environ.get("SEED_ADMIN_EMAIL", "admin@example.com")
DEFAULT_ADMIN_PASSWORD = os.environ.get("SEED_ADMIN_PASSWORD", "")


async def create_admin_user(
    db: AsyncSession,
    email: str | None = None,
    password: str | None = None,
    full_name: str = "Admin User",
) -> User:
    """Create admin user if not exists."""
    email = email or DEFAULT_ADMIN_EMAIL
    password = password or DEFAULT_ADMIN_PASSWORD
    result = await db.execute(select(User).where(User.email == email))
    existing = result.scalar_one_or_none()

    if existing:
        print(f"Admin user {mask_email(email)} already exists (id={existing.id})")
        return existing

    user = User(
        email=email,
        hashed_password=get_password_hash(password),
        full_name=full_name,
        is_active=True,
        is_superuser=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    print(f"Created admin user: {mask_email(email)} (id={user.id})")
    return user


async def create_default_workspace(db: AsyncSession) -> Workspace:
    """Create default workspace if not exists."""
    result = await db.execute(
        select(Workspace).where(Workspace.id == DEFAULT_WORKSPACE_ID)
    )
    existing = result.scalar_one_or_none()

    if existing:
        print(f"Default workspace already exists: {existing.name}")
        return existing

    workspace = Workspace(
        id=DEFAULT_WORKSPACE_ID,
        name="Default Workspace",
        slug="default",
        description="Default workspace for the application",
        is_active=True,
    )
    db.add(workspace)
    await db.commit()
    await db.refresh(workspace)
    print(f"Created default workspace: {workspace.name} (id={workspace.id})")
    return workspace


async def create_workspace_membership(
    db: AsyncSession,
    user: User,
    workspace: Workspace,
) -> WorkspaceMembership:
    """Create workspace membership if not exists."""
    result = await db.execute(
        select(WorkspaceMembership).where(
            WorkspaceMembership.user_id == user.id,
            WorkspaceMembership.workspace_id == workspace.id,
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        print(
            f"Membership already exists for user {mask_email(user.email)} "
            f"in {workspace.name}"
        )
        return existing

    membership = WorkspaceMembership(
        user_id=user.id,
        workspace_id=workspace.id,
        role="owner",
        is_default=True,
    )
    db.add(membership)
    await db.commit()
    await db.refresh(membership)
    print(
        f"Created membership for {mask_email(user.email)} "
        f"in {workspace.name} (role=owner)"
    )
    return membership


async def seed_database() -> None:
    """Seed database with initial data."""
    if not DEFAULT_ADMIN_PASSWORD:
        print(
            "ERROR: SEED_ADMIN_PASSWORD not set. "
            "Set the SEED_ADMIN_PASSWORD environment variable before seeding.",
            file=sys.stderr,
        )
        sys.exit(1)

    async with AsyncSessionLocal() as db:
        user = await create_admin_user(db)
        workspace = await create_default_workspace(db)
        await create_workspace_membership(db, user, workspace)
        print("\nSeeding complete!")


if __name__ == "__main__":
    asyncio.run(seed_database())
