"""Seed + authenticated smoke for the field-service job calendar.

This proves the end-to-end dispatch promise that unit tests only cover in
pieces: a dispatcher creates and assigns a job, and the *assigned worker* — a
separate login — then sees that job on **their** calendar via
``GET /jobs/calendar/mine``.

It runs in two phases:

1. **Seed** (idempotent, direct DB session, reusing ``app.db.seed`` helpers):
   - the dispatcher login (the seed admin, role ``owner``) + default workspace,
   - a **worker** login (role ``technician``) and a :class:`Technician` row
     whose ``user_id`` links to that worker — the link that makes
     ``/calendar/mine`` resolve to a signed-in user.

2. **Smoke** (HTTP against a running API): dispatcher logs in → creates a
   contact → creates a scheduled job → tags the worker's technician → worker
   logs in → ``/calendar/mine`` shows the job with the worker on it. It also
   asserts role gating (worker cannot dispatch → 403) and that the endpoints
   reject anonymous callers (401).

Usage::

    make dev                       # Postgres + API on :8000
    SEED_ADMIN_PASSWORD='<pw>' uv run python -m scripts.smoke_jobs_calendar

Environment:
    SMOKE_BASE_URL          API base URL (default http://localhost:8000)
    SEED_ADMIN_EMAIL/_PASSWORD   dispatcher login (password required)
    SMOKE_WORKER_EMAIL      worker login email (default field.worker@example.com)
    SMOKE_WORKER_PASSWORD   worker password (default: reuse SEED_ADMIN_PASSWORD)
    SMOKE_KEEP=1            leave the created job in place for UI inspection

Exit code is non-zero if any step fails, so it is safe to gate on in scripts.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import hash_value
from app.core.security import get_password_hash
from app.db.seed import (
    DEFAULT_ADMIN_EMAIL,
    DEFAULT_ADMIN_PASSWORD,
    DEFAULT_WORKSPACE_ID,
    create_admin_user,
    create_default_workspace,
    create_workspace_membership,
)
from app.db.session import AsyncSessionLocal
from app.models.field_service import Technician
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership
from app.utils.pii import mask_email

BASE_URL = os.environ.get("SMOKE_BASE_URL", "http://localhost:8000").rstrip("/")
WORKER_EMAIL = os.environ.get("SMOKE_WORKER_EMAIL", "field.worker@example.com")
WORKER_PASSWORD = os.environ.get("SMOKE_WORKER_PASSWORD") or DEFAULT_ADMIN_PASSWORD
WORKER_NAME = "Field Worker"
KEEP_JOB = os.environ.get("SMOKE_KEEP") == "1"

_API = f"{BASE_URL}/api/v1"
_WS = str(DEFAULT_WORKSPACE_ID)


class SmokeError(AssertionError):
    """A smoke assertion failed."""


_passed = 0


def _check(condition: bool, message: str) -> None:
    """Assert a smoke condition, printing a green tick or raising on failure."""
    global _passed
    if not condition:
        raise SmokeError(message)
    _passed += 1
    print(f"  \u2713 {message}")


# --------------------------------------------------------------------------- #
# Phase 1 — seed (idempotent)
# --------------------------------------------------------------------------- #
async def _seed_worker(db: AsyncSession, workspace: Workspace) -> tuple[User, Technician]:
    """Get-or-create the worker login + a technician linked to it.

    Mirrors ``app.db.seed`` conventions; ``email_hash`` is the indexed lookup
    column kept in sync by the ``User`` write-event listener.
    """
    result = await db.execute(select(User).where(User.email_hash == hash_value(WORKER_EMAIL)))
    worker = result.scalar_one_or_none()
    if worker is None:
        worker = User(
            email=WORKER_EMAIL,
            hashed_password=get_password_hash(WORKER_PASSWORD),
            full_name=WORKER_NAME,
            is_active=True,
            is_superuser=False,
        )
        db.add(worker)
        await db.flush()
        print(f"Created worker login: {mask_email(WORKER_EMAIL)} (id={worker.id})")
    else:
        print(f"Worker login {mask_email(WORKER_EMAIL)} already exists (id={worker.id})")

    membership = (
        await db.execute(
            select(WorkspaceMembership).where(
                WorkspaceMembership.user_id == worker.id,
                WorkspaceMembership.workspace_id == workspace.id,
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        db.add(
            WorkspaceMembership(
                user_id=worker.id,
                workspace_id=workspace.id,
                role="technician",
                is_default=True,
            )
        )
        print("Added worker membership (role=technician)")

    technician = (
        await db.execute(
            select(Technician).where(
                Technician.workspace_id == workspace.id,
                Technician.user_id == worker.id,
            )
        )
    ).scalar_one_or_none()
    if technician is None:
        technician = Technician(
            workspace_id=workspace.id,
            user_id=worker.id,
            name=WORKER_NAME,
            email=WORKER_EMAIL,
            color="#0ea5e9",
            is_active=True,
        )
        db.add(technician)
        await db.flush()
        print(f"Created technician linked to worker (id={technician.id})")
    else:
        print(f"Technician for worker already exists (id={technician.id})")

    await db.commit()
    await db.refresh(worker)
    await db.refresh(technician)
    return worker, technician


async def _seed() -> Technician:
    """Seed dispatcher + workspace + worker; return the worker's technician."""
    if not DEFAULT_ADMIN_PASSWORD:
        print(
            "ERROR: SEED_ADMIN_PASSWORD not set. Export it before running the smoke.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    print("Seeding dispatcher + worker + technician (idempotent)\u2026")
    async with AsyncSessionLocal() as db:
        admin = await create_admin_user(db)
        workspace = await create_default_workspace(db)
        await create_workspace_membership(db, admin, workspace)
        _, technician = await _seed_worker(db, workspace)
    return technician


# --------------------------------------------------------------------------- #
# Phase 2 — HTTP smoke
# --------------------------------------------------------------------------- #
async def _login(client: httpx.AsyncClient, email: str, password: str) -> str:
    """Exchange credentials for a bearer token (native-caller body token)."""
    response = await client.post(
        f"{_API}/auth/login",
        data={"username": email, "password": password},
    )
    response.raise_for_status()
    token = response.json().get("access_token")
    if not token:
        raise SmokeError(f"login for {mask_email(email)} returned no access_token")
    # Login also sets an httpOnly access_token cookie, which the API *prefers*
    # over the Authorization header. Drop it so each request authenticates only
    # via its explicit Bearer header (the native-caller path under test) and a
    # stale cookie can't impersonate a different identity.
    client.cookies.clear()
    return str(token)


async def _run_smoke(technician: Technician) -> None:
    technician_id = str(technician.id)
    async with httpx.AsyncClient(timeout=15.0) as client:
        # --- dispatcher actions -------------------------------------------- #
        admin_token = await _login(client, DEFAULT_ADMIN_EMAIL, DEFAULT_ADMIN_PASSWORD)
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        print("\nDispatcher flow")

        contact_resp = await client.post(
            f"{_API}/workspaces/{_WS}/contacts",
            headers=admin_headers,
            json={
                "first_name": "Dispatch",
                "last_name": "Smoke",
                "phone_number": "+15555550100",
            },
        )
        _check(
            contact_resp.status_code == 201,
            f"create contact -> 201 (got {contact_resp.status_code})",
        )
        contact_id = contact_resp.json()["id"]

        start = (datetime.now(UTC) + timedelta(days=1)).replace(microsecond=0)
        end = start + timedelta(hours=2)
        job_resp = await client.post(
            f"{_API}/workspaces/{_WS}/jobs",
            headers=admin_headers,
            json={
                "contact_id": contact_id,
                "title": "Smoke test work order",
                "description": "Created by smoke_jobs_calendar.py",
                "scheduled_start": start.isoformat(),
                "scheduled_end": end.isoformat(),
            },
        )
        _check(
            job_resp.status_code == 201, f"create scheduled job -> 201 (got {job_resp.status_code})"
        )
        job = job_resp.json()
        job_id = job["id"]
        _check(job["status"] == "scheduled", f"job derives status=scheduled (got {job['status']})")

        assign_resp = await client.post(
            f"{_API}/workspaces/{_WS}/jobs/{job_id}/assignments",
            headers=admin_headers,
            json={"technician_ids": [technician_id]},
        )
        _check(
            assign_resp.status_code == 200,
            f"assign technician -> 200 (got {assign_resp.status_code})",
        )
        assigned_ids = {tech["id"] for tech in assign_resp.json().get("technicians", [])}
        _check(technician_id in assigned_ids, "assigned job lists the worker's technician")

        # --- the worker sees it on *their* calendar ------------------------ #
        print("\nWorker calendar")
        worker_token = await _login(client, WORKER_EMAIL, WORKER_PASSWORD)
        worker_headers = {"Authorization": f"Bearer {worker_token}"}

        window_from = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        window_to = (datetime.now(UTC) + timedelta(days=8)).isoformat()
        mine_resp = await client.get(
            f"{_API}/workspaces/{_WS}/jobs/calendar/mine",
            headers=worker_headers,
            params={"date_from": window_from, "date_to": window_to},
        )
        _check(
            mine_resp.status_code == 200, f"GET /calendar/mine -> 200 (got {mine_resp.status_code})"
        )
        mine = mine_resp.json()
        mine_ids = {item["id"] for item in mine["items"]}
        _check(job_id in mine_ids, "the assigned job appears on the worker's calendar")
        mine_job = next(item for item in mine["items"] if item["id"] == job_id)
        _check(
            technician_id in {tech["id"] for tech in mine_job.get("technicians", [])},
            "the worker is shown as assigned on their calendar entry",
        )

        # --- guardrails ---------------------------------------------------- #
        print("\nGuardrails")
        forbidden = await client.post(
            f"{_API}/workspaces/{_WS}/jobs",
            headers=worker_headers,
            json={"contact_id": contact_id, "title": "Worker should not dispatch"},
        )
        _check(
            forbidden.status_code == 403,
            f"worker cannot dispatch -> 403 (got {forbidden.status_code})",
        )

        # A fresh client so prior logins' httpOnly cookies don't leak in and
        # make this "anonymous" request authenticated.
        async with httpx.AsyncClient(timeout=15.0) as anon_client:
            anon = await anon_client.get(f"{_API}/workspaces/{_WS}/jobs")
        _check(anon.status_code == 401, f"anonymous list -> 401 (got {anon.status_code})")

        # --- cleanup ------------------------------------------------------- #
        if KEEP_JOB:
            print(f"\nSMOKE_KEEP=1 \u2014 leaving job {job_id} in place for UI inspection")
        else:
            deleted = await client.delete(
                f"{_API}/workspaces/{_WS}/jobs/{job_id}",
                headers=admin_headers,
            )
            _check(
                deleted.status_code == 204, f"cleanup delete job -> 204 (got {deleted.status_code})"
            )


async def _main() -> int:
    technician = await _seed()
    try:
        await _run_smoke(technician)
    except httpx.ConnectError:
        print(
            f"\n\u2717 Could not reach {BASE_URL}. Start the API first (e.g. `make dev`).",
            file=sys.stderr,
        )
        return 1
    except (SmokeError, httpx.HTTPStatusError) as exc:
        print(f"\n\u2717 Smoke failed: {exc}", file=sys.stderr)
        return 1
    print(f"\n\u2713 Job-calendar smoke passed ({_passed} checks).")
    return 0


def main() -> None:
    """Console entry point."""
    raise SystemExit(asyncio.run(_main()))


if __name__ == "__main__":
    main()
