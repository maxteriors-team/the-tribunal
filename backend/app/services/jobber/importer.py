"""Idempotent, workspace-scoped one-time import of Jobber business records.

This is the **one-time historical migration** companion to
:mod:`app.services.jobber.sync` (which keeps technicians in step). It pulls
Jobber's customer-facing records into the CRM so the workspace can retire Jobber:

- Jobber **clients -> contacts** (+ their **properties -> service_locations**),
- Jobber **jobs -> field_service_jobs** (resolving the customer/site FKs and
  tagging technicians previously synced by ``Technician.external_id``),
- Jobber **open invoices -> invoices** (historical / AR visibility only -- these
  are *never* sent or re-billed; Tribunal is the sole biller after cutover).

Design mirrors :class:`app.services.jobber.sync.JobberTechnicianSync`:

- **Idempotency** keys on ``(workspace_id, external_source='jobber',
  external_id)`` per table, backed by the partial-unique indexes added in
  migration ``b8b15c8633c6``. Re-running upserts the same rows -- the second run
  creates **zero** duplicates.
- **Pure mapping** lives in :mod:`app.services.jobber.mapping`; this module owns
  persistence, FK resolution across entities, and the create/update accounting.
- Inputs are async iterators (live :class:`JobberClient`) **or** plain iterables
  (replays / tests), so the same code path proves out without a live token.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterable, Iterable
from dataclasses import asdict, dataclass, field
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.models.field_service import Job, JobAssignment, ServiceLocation, Technician
from app.models.invoice import Invoice
from app.services.contacts.contact_import import clean_phone_number
from app.services.jobber.mapping import (
    EXTERNAL_SOURCE,
    JobberMappingError,
    jobber_client_properties,
    jobber_client_to_contact_data,
    jobber_invoice_to_invoice_data,
    jobber_job_to_job_data,
    jobber_property_to_location_data,
)

logger = structlog.get_logger()

# Owned fields per entity. Re-running the import refreshes only these on an
# existing row, so local edits to anything else survive a re-import.
_CONTACT_FIELDS = ("first_name", "last_name", "company_name", "email", "phone_number")
_CONTACT_ADDRESS_FIELDS = (
    "address_line1",
    "address_line2",
    "address_city",
    "address_state",
    "address_zip",
)
_LOCATION_FIELDS = ("name", "address_line1", "address_line2", "city", "state", "postal_code")
_JOB_FIELDS = ("title", "description", "status", "scheduled_start", "scheduled_end")
_INVOICE_FIELDS = (
    "number",
    "status",
    "subtotal",
    "tax_amount",
    "discount_amount",
    "total",
    "amount_paid",
)


@dataclass
class EntityCounts:
    """Create/update/unchanged/skipped tally for one imported entity type."""

    created: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0


@dataclass
class JobberImportResult:
    """Per-entity outcome of an import run (counts + collected skip reasons)."""

    contacts: EntityCounts = field(default_factory=EntityCounts)
    properties: EntityCounts = field(default_factory=EntityCounts)
    jobs: EntityCounts = field(default_factory=EntityCounts)
    invoices: EntityCounts = field(default_factory=EntityCounts)
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "contacts": asdict(self.contacts),
            "properties": asdict(self.properties),
            "jobs": asdict(self.jobs),
            "invoices": asdict(self.invoices),
            "errors": self.errors,
        }


class JobberImporter:
    """Upserts Jobber clients/properties/jobs/invoices into one workspace."""

    def __init__(self, db: AsyncSession, workspace_id: uuid.UUID) -> None:
        self.db = db
        self.workspace_id = workspace_id
        self.result = JobberImportResult()
        # Filled as clients import; reused to resolve job/invoice FKs in the same
        # run. Seeded from the DB so a jobs-only re-run still resolves contacts.
        self._contacts: dict[str, Contact] = {}
        self._locations: dict[str, ServiceLocation] = {}
        self._technicians: dict[str, Technician] = {}

    # ---- existing-row loaders (idempotency lookups) ----------------------- #
    async def _load_existing(self, model: Any) -> dict[str, Any]:
        """All Jobber-sourced rows of ``model`` in this workspace, keyed by ext id."""
        rows = (
            (
                await self.db.execute(
                    select(model).where(
                        model.workspace_id == self.workspace_id,
                        model.external_source == EXTERNAL_SOURCE,
                    )
                )
            )
            .scalars()
            .all()
        )
        return {row.external_id: row for row in rows if row.external_id}

    @staticmethod
    def _apply(row: Any, data: dict[str, Any], fields: tuple[str, ...]) -> bool:
        """Copy ``fields`` from ``data`` onto ``row``; return whether anything changed."""
        changed = False
        for f in fields:
            if f in data and getattr(row, f) != data[f]:
                setattr(row, f, data[f])
                changed = True
        return changed

    # ---- clients (+ their properties) ------------------------------------- #
    async def import_clients(
        self, clients: AsyncIterable[dict[str, Any]] | Iterable[dict[str, Any]]
    ) -> None:
        """Upsert Jobber clients into contacts and their properties into sites."""
        self._contacts = await self._load_existing(Contact)
        self._locations = await self._load_existing(ServiceLocation)

        async for node in _aiter(clients):
            contact = await self._upsert_contact(node)
            if contact is None:
                continue
            for prop in jobber_client_properties(node):
                self._upsert_location(prop, contact)

        await self.db.flush()

    async def _upsert_contact(self, node: dict[str, Any]) -> Contact | None:
        try:
            data = jobber_client_to_contact_data(node)
        except JobberMappingError as exc:
            self.result.contacts.skipped += 1
            self.result.errors.append(str(exc))
            return None

        # Contact.phone_number is NOT NULL (drives voice/SMS). A client with no
        # usable phone is surfaced as skipped rather than dropped silently.
        phone = clean_phone_number(data.get("phone") or "")
        if not phone:
            self.result.contacts.skipped += 1
            self.result.errors.append(
                f"Jobber client {data['external_id']!r} has no usable phone number"
            )
            return None

        ext_id = data["external_id"]
        persist = {
            "first_name": data["first_name"],
            "last_name": data["last_name"],
            "company_name": data["company_name"],
            "email": data["email"],
            "phone_number": phone,
            "address_line1": data["address_line1"],
            "address_line2": data["address_line2"],
            "address_city": data["address_city"],
            "address_state": data["address_state"],
            "address_zip": data["address_zip"],
        }

        existing = self._contacts.get(ext_id)
        if existing is None:
            contact = Contact(
                workspace_id=self.workspace_id,
                source=EXTERNAL_SOURCE,
                external_source=EXTERNAL_SOURCE,
                external_id=ext_id,
                **persist,
            )
            self.db.add(contact)
            self._contacts[ext_id] = contact
            self.result.contacts.created += 1
            return contact

        changed = self._apply(existing, persist, _CONTACT_FIELDS + _CONTACT_ADDRESS_FIELDS)
        if changed:
            self.result.contacts.updated += 1
        else:
            self.result.contacts.unchanged += 1
        return existing

    def _upsert_location(self, node: dict[str, Any], contact: Contact) -> None:
        try:
            data = jobber_property_to_location_data(node)
        except JobberMappingError as exc:
            self.result.properties.skipped += 1
            self.result.errors.append(str(exc))
            return

        ext_id = data["external_id"]
        existing = self._locations.get(ext_id)
        if existing is None:
            location = ServiceLocation(
                workspace_id=self.workspace_id,
                contact=contact,
                external_source=EXTERNAL_SOURCE,
                external_id=ext_id,
                **{k: v for k, v in data.items() if k not in ("external_source", "external_id")},
            )
            self.db.add(location)
            self._locations[ext_id] = location
            self.result.properties.created += 1
            return

        changed = self._apply(existing, data, _LOCATION_FIELDS)
        if changed:
            self.result.properties.updated += 1
        else:
            self.result.properties.unchanged += 1

    # ---- jobs ------------------------------------------------------------- #
    async def import_jobs(
        self, jobs: AsyncIterable[dict[str, Any]] | Iterable[dict[str, Any]]
    ) -> None:
        """Upsert Jobber jobs, resolving customer/site/technician references."""
        existing_jobs = await self._load_existing(Job)
        # Refresh FK-resolution maps from the DB so a jobs-only run still works.
        if not self._contacts:
            self._contacts = await self._load_existing(Contact)
        if not self._locations:
            self._locations = await self._load_existing(ServiceLocation)
        self._technicians = await self._load_existing(Technician)

        async for node in _aiter(jobs):
            try:
                data = jobber_job_to_job_data(node)
            except JobberMappingError as exc:
                self.result.jobs.skipped += 1
                self.result.errors.append(str(exc))
                continue

            contact = self._contacts.get(data["client_external_id"])
            if contact is None:
                self.result.jobs.skipped += 1
                self.result.errors.append(
                    f"Jobber job {data['external_id']!r} references unimported "
                    f"client {data['client_external_id']!r}"
                )
                continue

            location = self._locations.get(data["property_external_id"] or "")
            persist = {k: data[k] for k in _JOB_FIELDS}

            ext_id = data["external_id"]
            existing = existing_jobs.get(ext_id)
            if existing is None:
                job = Job(
                    workspace_id=self.workspace_id,
                    contact=contact,
                    service_location=location,
                    external_source=EXTERNAL_SOURCE,
                    external_id=ext_id,
                    **persist,
                )
                self.db.add(job)
                await self.db.flush()
                existing_jobs[ext_id] = job
                self._assign_technicians(job, data["assigned_user_external_ids"], existing=set())
                self.result.jobs.created += 1
                continue

            changed = self._apply(existing, persist, _JOB_FIELDS)
            if existing.service_location_id is None and location is not None:
                existing.service_location = location
                changed = True
            assigned_changed = await self._sync_job_assignments(
                existing, data["assigned_user_external_ids"]
            )
            if changed or assigned_changed:
                self.result.jobs.updated += 1
            else:
                self.result.jobs.unchanged += 1

        await self.db.flush()

    def _assign_technicians(
        self, job: Job, technician_ext_ids: list[str], *, existing: set[uuid.UUID]
    ) -> int:
        """Add assignment rows for the given technician ext ids; return how many added."""
        added = 0
        for tech_ext_id in technician_ext_ids:
            technician = self._technicians.get(tech_ext_id)
            if technician is None or technician.id in existing:
                continue
            self.db.add(JobAssignment(job_id=job.id, technician_id=technician.id))
            existing.add(technician.id)
            added += 1
        return added

    async def _sync_job_assignments(self, job: Job, technician_ext_ids: list[str]) -> bool:
        """Add any missing technician tags on an existing job (never removes)."""
        rows: list[JobAssignment] = list(
            (await self.db.execute(select(JobAssignment).where(JobAssignment.job_id == job.id)))
            .scalars()
            .all()
        )
        current = {row.technician_id for row in rows}
        added = self._assign_technicians(job, technician_ext_ids, existing=current)
        return added > 0

    # ---- invoices (historical / AR only) ---------------------------------- #
    async def import_invoices(
        self, invoices: AsyncIterable[dict[str, Any]] | Iterable[dict[str, Any]]
    ) -> None:
        """Upsert Jobber invoices as historical/AR records (never re-billed)."""
        existing_invoices = await self._load_existing(Invoice)
        if not self._contacts:
            self._contacts = await self._load_existing(Contact)

        async for node in _aiter(invoices):
            try:
                data = jobber_invoice_to_invoice_data(node)
            except JobberMappingError as exc:
                self.result.invoices.skipped += 1
                self.result.errors.append(str(exc))
                continue

            contact = self._contacts.get(data["client_external_id"] or "")
            persist = {k: data[k] for k in _INVOICE_FIELDS}
            persist["issue_date"] = data["issue_date"]
            persist["due_date"] = data["due_date"]
            persist["notes"] = data["notes"]

            ext_id = data["external_id"]
            existing = existing_invoices.get(ext_id)
            if existing is None:
                invoice = Invoice(
                    workspace_id=self.workspace_id,
                    contact_id=contact.id if contact is not None else None,
                    external_source=EXTERNAL_SOURCE,
                    external_id=ext_id,
                    **persist,
                )
                self.db.add(invoice)
                existing_invoices[ext_id] = invoice
                self.result.invoices.created += 1
                continue

            changed = self._apply(
                existing, persist, _INVOICE_FIELDS + ("issue_date", "due_date", "notes")
            )
            if existing.contact_id is None and contact is not None:
                existing.contact_id = contact.id
                changed = True
            if changed:
                self.result.invoices.updated += 1
            else:
                self.result.invoices.unchanged += 1

        await self.db.flush()


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
async def _aiter(
    source: AsyncIterable[dict[str, Any]] | Iterable[dict[str, Any]],
) -> AsyncIterable[dict[str, Any]]:
    """Adapt a sync or async iterable to a uniform async iterator."""
    if isinstance(source, AsyncIterable):
        async for item in source:
            yield item
    else:
        for item in source:
            yield item
