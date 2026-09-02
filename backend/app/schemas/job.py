"""Schemas for field-service jobs (work orders) and worker assignments.

A *job* is a unit of field work for a customer. Dispatch tags one or more
technicians to it and gives it a time window; each assigned worker then sees the
job on their calendar. Status is derived/maintained server-side by
:class:`app.services.jobs.JobService`, never set directly by API callers.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.models.field_service import JobStatus
from app.schemas.lighting_project import (
    DesignSchema,
    DocumentSettingsSchema,
    DocumentText,
    PhotoSchema,
    SheetMetadataSchema,
    ShortText,
)
from app.schemas.quote import QuoteStatus


class JobCreate(BaseModel):
    """Create a job. Optionally pre-scheduled and/or pre-assigned to workers."""

    contact_id: int = Field(..., description="Owning customer contact id")
    service_location_id: uuid.UUID | None = Field(None, description="Job site")
    crew_id: uuid.UUID | None = Field(None, description="Optional dispatch lane/crew")
    business_location_id: uuid.UUID | None = Field(
        None, description="Optional business location (branch)"
    )
    title: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(None, max_length=5000)
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None
    technician_ids: list[uuid.UUID] = Field(
        default_factory=list, description="Technicians to tag onto this job"
    )

    @model_validator(mode="after")
    def _check_window(self) -> "JobCreate":
        """Both ends of a time window must be supplied together and ordered."""
        if (self.scheduled_start is None) != (self.scheduled_end is None):
            raise ValueError("scheduled_start and scheduled_end must be provided together")
        if (
            self.scheduled_start is not None
            and self.scheduled_end is not None
            and self.scheduled_end <= self.scheduled_start
        ):
            raise ValueError("scheduled_end must be after scheduled_start")
        return self


class JobUpdate(BaseModel):
    """Partial update for a job. Status is recomputed from the time window."""

    service_location_id: uuid.UUID | None = None
    crew_id: uuid.UUID | None = None
    business_location_id: uuid.UUID | None = None
    invoice_id: uuid.UUID | None = Field(None, description="Link this job to a billing invoice")
    title: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=5000)
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None
    status: JobStatus | None = Field(
        None,
        description="Advance lifecycle (e.g. in_progress/completed/cancelled)",
    )


class JobScheduleRequest(BaseModel):
    """Set a job's time window (flips unscheduled -> scheduled)."""

    scheduled_start: datetime
    scheduled_end: datetime

    @model_validator(mode="after")
    def _check_order(self) -> "JobScheduleRequest":
        if self.scheduled_end <= self.scheduled_start:
            raise ValueError("scheduled_end must be after scheduled_start")
        return self


class JobVisitCreate(BaseModel):
    """Add a scheduled visit to a job."""

    starts_at: datetime
    ends_at: datetime
    anytime: bool = False
    instructions: str | None = Field(None, max_length=5000)

    @model_validator(mode="after")
    def _check_order(self) -> "JobVisitCreate":
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class JobVisitUpdate(BaseModel):
    """Update a visit window, instructions, or lifecycle status."""

    starts_at: datetime | None = None
    ends_at: datetime | None = None
    anytime: bool | None = None
    instructions: str | None = Field(None, max_length=5000)
    status: JobStatus | None = None


class JobVisitResponse(BaseModel):
    id: uuid.UUID
    job_id: uuid.UUID
    starts_at: datetime
    ends_at: datetime
    anytime: bool
    instructions: str | None
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class JobPricedLineItemInput(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(None, max_length=2000)
    quantity: Decimal = Field(..., gt=0, max_digits=12, decimal_places=2)
    unit_price: Decimal = Field(..., ge=0, max_digits=12, decimal_places=2)
    taxable: bool = True


class JobPricingReplace(BaseModel):
    """Replace priced scope atomically; omitted rows are deleted."""

    tax_rate: Decimal = Field(Decimal("0.00"), ge=0, le=100, max_digits=5, decimal_places=2)
    items: list[JobPricedLineItemInput] = Field(default_factory=list, max_length=200)


class JobPricedLineItemResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    quantity: Decimal
    unit_price: Decimal
    taxable: bool
    position: int
    total: Decimal


class JobPricingResponse(BaseModel):
    job_id: uuid.UUID
    tax_rate: Decimal
    items: list[JobPricedLineItemResponse]
    subtotal: Decimal
    discount: Decimal = Decimal("0.00")
    tax: Decimal
    total: Decimal


class JobAssignRequest(BaseModel):
    """Tag one or more technicians onto a job."""

    technician_ids: list[uuid.UUID] = Field(..., min_length=1)


class TechnicianSummary(BaseModel):
    """Compact technician view for rendering avatars/chips on the calendar."""

    id: uuid.UUID
    name: str
    color: str

    model_config = {"from_attributes": True}


class JobSiteSummary(BaseModel):
    """Where the work happens, as a field worker needs it.

    Embedded on the job because the field tier holds ``jobs:read`` only: a
    technician is denied ``GET /workspaces/{id}/service-locations`` and
    ``/contacts`` (both ``crm:read``), so they cannot resolve the site
    themselves. Address and access notes are decrypted by the ORM on read.

    Operational fields only — address, access notes, map pin. No pricing, and
    no customer CRM state.
    """

    id: uuid.UUID
    name: str | None = None
    address_line1: str | None = None
    address_line2: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    country: str | None = None
    # Gate codes, pets, parking — what the tech needs to get on site.
    access_notes: str | None = None
    # Map pin for routing.
    latitude: float | None = None
    longitude: float | None = None

    model_config = {"from_attributes": True}


class JobCustomerSummary(BaseModel):
    """Who to meet on site, and how to reach them.

    Deliberately the *narrowest* customer projection in the API — name and phone
    only. It is served to the field tier, which has no ``crm:read``, so it must
    not become a back door onto the contact record: no email, lead score, status,
    tags, notes, or lifecycle. Widen this only with an explicit field-workflow
    reason.
    """

    id: int
    name: str = Field(..., description="Customer display name")
    phone_number: str | None = Field(None, description="Direct line for the tech on site")


class JobLineItemSummary(BaseModel):
    """One unit of scope of work — deliberately price-free.

    Projected from the job's priced scope, accepted quote, or linked invoice. A
    separate schema from their priced responses **on purpose**: those carry
    ``unit_price``, ``discount``, and ``total``, and a field technician must never
    receive money on a job payload. This projection only governs what rides on
    the job.

    Adding a money field here leaks it to every technician — don't.
    """

    id: uuid.UUID
    name: str
    description: str | None = None
    quantity: float

    model_config = {"from_attributes": True}


class JobResponse(BaseModel):
    """Job response: the work order plus everything needed to execute it.

    Carries the job site, the customer's name/phone, and the scope of work so a
    field technician — who holds ``jobs:read`` and nothing else — can answer
    "what am I doing, and where" from this payload alone. Every embedded
    projection is price-free.
    """

    id: uuid.UUID
    workspace_id: uuid.UUID
    contact_id: int
    service_location_id: uuid.UUID | None
    crew_id: uuid.UUID | None
    business_location_id: uuid.UUID | None = None
    invoice_id: uuid.UUID | None = None
    source_quote_id: uuid.UUID | None = None
    lighting_project_id: uuid.UUID | None = None
    title: str
    description: str | None
    status: JobStatus
    scheduled_start: datetime | None
    scheduled_end: datetime | None
    external_source: str | None
    external_id: str | None
    technicians: list[TechnicianSummary] = Field(default_factory=list)
    # Null when the job has no site linked (``service_location_id`` is nullable).
    service_location: JobSiteSummary | None = None
    customer: JobCustomerSummary | None = None
    # Empty when the job has no linked invoice, or that invoice has no lines.
    line_items: list[JobLineItemSummary] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class JobListResponse(BaseModel):
    """List of jobs."""

    items: list[JobResponse]
    total: int


class InstallationPlanFixture(BaseModel):
    """Price-free fixture schedule row for the selected installation sheet."""

    number: int
    item_id: ShortText
    product_id: ShortText
    catalog_item_id: ShortText | None = None
    catalog_sku: ShortText | None = None
    lamp_catalog_item_id: ShortText | None = None
    accessory_catalog_item_ids: list[ShortText] = Field(default_factory=list)
    circuit_id: ShortText | None = None
    transformer_zone_id: ShortText | None = None


JobPaymentStatus = Literal["not_required", "pending", "paid"]


class JobInstallationPlanResponse(BaseModel):
    """Assignment-scoped, price-free plan with the customer's proposal decision."""

    job_id: uuid.UUID
    project_id: uuid.UUID
    project_name: str
    project_version: int
    project_updated_at: datetime
    selected_shot_id: ShortText
    proposal_preview_image: str | None = None
    proposal_preview_caption: str | None = None
    proposal_status: QuoteStatus | None = None
    proposal_accepted_at: datetime | None = None
    payment_status: JobPaymentStatus | None = None
    payment_received_at: datetime | None = None
    sheet_label: ShortText | None = None
    drawing_title: ShortText | None = None
    drawing_number: ShortText | None = None
    sheet: SheetMetadataSchema | None = None
    photo: PhotoSchema
    design: DesignSchema
    dusk: float
    settings: DocumentSettingsSchema
    fixture_schedule: list[InstallationPlanFixture] = Field(default_factory=list)
    precon_field_brief: DocumentText = ""
