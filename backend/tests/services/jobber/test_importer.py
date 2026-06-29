"""Real-DB integration tests for :class:`JobberImporter`.

The whole point of the importer is idempotent persistence across encrypted
columns, the per-table partial-unique indexes, and cross-entity FK resolution
(jobs/invoices -> contacts/locations/technicians). None of that is meaningfully
testable against a mock session, so these hit Postgres and are marked
``integration`` (run with ``pytest -m integration``).

The decisive assertion is the Phase 2 exit criterion: running the import twice
creates **zero** duplicates the second time.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal, engine
from app.models.contact import Contact
from app.models.field_service import Job, JobAssignment, ServiceLocation, Technician
from app.models.invoice import Invoice
from app.models.workspace import Workspace
from app.services.jobber.importer import JobberImporter
from app.services.jobber.mapping import EXTERNAL_SOURCE

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest.fixture(autouse=True)
async def _fresh_engine_pool() -> AsyncIterator[None]:
    await engine.dispose()
    yield
    await engine.dispose()


async def _make_workspace(db: AsyncSession) -> Workspace:
    ws = Workspace(id=uuid.uuid4(), name="Jobber Co", slug=f"jb-{uuid.uuid4().hex[:8]}")
    db.add(ws)
    await db.flush()
    return ws


def _client_node(ext: str, *, phone: str = "(512) 555-0142") -> dict:
    return {
        "id": ext,
        "firstName": "Jane",
        "lastName": "Homeowner",
        "companyName": None,
        "emails": [{"primary": True, "address": f"{ext}@example.com"}],
        "phones": [{"primary": True, "number": phone}],
        "billingAddress": {
            "street1": "12 Oak St",
            "city": "Austin",
            "province": "TX",
            "postalCode": "78701",
            "country": "US",
        },
        "clientProperties": {
            "nodes": [
                {
                    "id": f"{ext}-P1",
                    "address": {
                        "street1": "12 Oak St",
                        "city": "Austin",
                        "province": "TX",
                        "postalCode": "78701",
                        "country": "US",
                    },
                }
            ]
        },
    }


def _job_node(ext: str, client_ext: str, prop_ext: str, *, user_ext: str | None = None) -> dict:
    return {
        "id": ext,
        "jobNumber": 101,
        "title": "Gutter cleaning",
        "instructions": "2-story",
        "jobStatus": "active",
        "startAt": "2026-06-30T14:00:00Z",
        "endAt": "2026-06-30T16:00:00Z",
        "client": {"id": client_ext},
        "property": {"id": prop_ext},
        "assignedUsers": {"nodes": [{"id": user_ext}] if user_ext else []},
    }


def _invoice_node(ext: str, client_ext: str) -> dict:
    return {
        "id": ext,
        "invoiceNumber": f"JB-{ext}",
        "invoiceStatus": "awaiting_payment",
        "issuedDate": "2026-06-01",
        "dueDate": "2026-06-15",
        "message": "Imported from Jobber",
        "client": {"id": client_ext},
        "amounts": {"total": 450.0, "subtotal": 410.0, "taxAmount": 40.0, "paymentsTotal": 0.0},
    }


async def _count(db: AsyncSession, model, workspace_id: uuid.UUID) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(model)
            .where(model.workspace_id == workspace_id, model.external_source == EXTERNAL_SOURCE)
        )
    ).scalar_one()


async def test_imports_clients_properties_jobs_invoices() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        # A technician previously synced from Jobber so job assignment resolves.
        tech = Technician(
            workspace_id=ws.id,
            name="Dana Tech",
            external_source=EXTERNAL_SOURCE,
            external_id="U1",
        )
        db.add(tech)
        await db.flush()

        importer = JobberImporter(db, ws.id)
        await importer.import_clients([_client_node("C1")])
        await importer.import_jobs([_job_node("J1", "C1", "C1-P1", user_ext="U1")])
        await importer.import_invoices([_invoice_node("I1", "C1")])
        await db.commit()

        assert importer.result.contacts.created == 1
        assert importer.result.properties.created == 1
        assert importer.result.jobs.created == 1
        assert importer.result.invoices.created == 1

        # The contact decrypts and the job resolved its FKs + technician tag.
        contact = (
            await db.execute(
                select(Contact).where(Contact.workspace_id == ws.id, Contact.external_id == "C1")
            )
        ).scalar_one()
        assert contact.first_name == "Jane"
        assert contact.email == "C1@example.com"
        assert contact.source == EXTERNAL_SOURCE

        job = (
            await db.execute(select(Job).where(Job.workspace_id == ws.id, Job.external_id == "J1"))
        ).scalar_one()
        assert job.contact_id == contact.id
        assert job.service_location_id is not None

        assignments = (
            (await db.execute(select(JobAssignment).where(JobAssignment.job_id == job.id)))
            .scalars()
            .all()
        )
        assert len(assignments) == 1
        assert assignments[0].technician_id == tech.id

        invoice = (
            await db.execute(
                select(Invoice).where(Invoice.workspace_id == ws.id, Invoice.external_id == "I1")
            )
        ).scalar_one()
        assert invoice.contact_id == contact.id
        assert float(invoice.total) == 450.0
        assert invoice.status == "sent"


async def test_reimport_creates_zero_duplicates() -> None:
    """Phase 2 exit criterion: a second identical import is a pure no-op."""
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        tech = Technician(
            workspace_id=ws.id,
            name="Dana Tech",
            external_source=EXTERNAL_SOURCE,
            external_id="U1",
        )
        db.add(tech)
        await db.flush()

        clients = [_client_node("C1"), _client_node("C2")]
        jobs = [_job_node("J1", "C1", "C1-P1", user_ext="U1")]
        invoices = [_invoice_node("I1", "C1")]

        first = JobberImporter(db, ws.id)
        await first.import_clients(clients)
        await first.import_jobs(jobs)
        await first.import_invoices(invoices)
        await db.commit()

        counts_after_first = {
            "contacts": await _count(db, Contact, ws.id),
            "locations": await _count(db, ServiceLocation, ws.id),
            "jobs": await _count(db, Job, ws.id),
            "invoices": await _count(db, Invoice, ws.id),
        }
        assert counts_after_first == {"contacts": 2, "locations": 2, "jobs": 1, "invoices": 1}

        # Re-run the exact same feed.
        second = JobberImporter(db, ws.id)
        await second.import_clients(clients)
        await second.import_jobs(jobs)
        await second.import_invoices(invoices)
        await db.commit()

        # Nothing created the second time; everything resolves as unchanged.
        assert second.result.contacts.created == 0
        assert second.result.properties.created == 0
        assert second.result.jobs.created == 0
        assert second.result.invoices.created == 0
        assert second.result.contacts.unchanged == 2

        # Row counts are identical -> zero duplicates.
        counts_after_second = {
            "contacts": await _count(db, Contact, ws.id),
            "locations": await _count(db, ServiceLocation, ws.id),
            "jobs": await _count(db, Job, ws.id),
            "invoices": await _count(db, Invoice, ws.id),
        }
        assert counts_after_second == counts_after_first

        # The technician tag was not duplicated either.
        job = (
            await db.execute(select(Job).where(Job.workspace_id == ws.id, Job.external_id == "J1"))
        ).scalar_one()
        tag_count = (
            await db.execute(
                select(func.count())
                .select_from(JobAssignment)
                .where(JobAssignment.job_id == job.id)
            )
        ).scalar_one()
        assert tag_count == 1


async def test_reimport_applies_field_updates() -> None:
    """A changed source field updates in place (no duplicate row)."""
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)

        importer = JobberImporter(db, ws.id)
        await importer.import_clients([_client_node("C1")])
        await db.commit()

        changed = _client_node("C1")
        changed["lastName"] = "Renter"
        again = JobberImporter(db, ws.id)
        await again.import_clients([changed])
        await db.commit()

        assert again.result.contacts.updated == 1
        assert again.result.contacts.created == 0
        contact = (
            await db.execute(
                select(Contact).where(Contact.workspace_id == ws.id, Contact.external_id == "C1")
            )
        ).scalar_one()
        assert contact.last_name == "Renter"
        assert await _count(db, Contact, ws.id) == 1


async def test_job_referencing_unimported_client_is_skipped() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        importer = JobberImporter(db, ws.id)
        await importer.import_jobs([_job_node("J1", "C-missing", "P-missing")])
        await db.commit()

        assert importer.result.jobs.created == 0
        assert importer.result.jobs.skipped == 1
        assert await _count(db, Job, ws.id) == 0


async def test_client_without_phone_is_skipped() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        node = _client_node("C1")
        node["phones"] = []  # contacts require a phone for voice/SMS follow-up
        importer = JobberImporter(db, ws.id)
        await importer.import_clients([node])
        await db.commit()

        assert importer.result.contacts.created == 0
        assert importer.result.contacts.skipped == 1
        assert await _count(db, Contact, ws.id) == 0
