"""Schemas for neighbor outreach: workspace settings, batches, entries, export.

Two groups live here:

- **Settings** (:class:`NeighborOutreachSettings` / ``...Update``) — the per-workspace
  JSONB config read through
  :mod:`app.services.field_service.neighbor_outreach_config`, mirroring
  :mod:`app.schemas.pricing` / :mod:`app.schemas.quote_revival`.
- **Runtime payloads** — the generated batch, its entries, per-entry status
  updates, and the print/canvass export.

The export is the one place a neighbour's street address crosses the API boundary.
That is deliberate and is the whole point of a door-hanger list, but it means the
export rows are PII: they are served only to an authenticated dispatcher for their
own workspace, and never written to ``backend/static/``.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.neighbor_outreach import NeighborOutreachChannel, NeighborOutreachStatus
from app.services.field_service.jobsite_radius import (
    DEFAULT_MAX_NEIGHBORS,
    DEFAULT_RADIUS_METERS,
    MAX_NEIGHBORS_CEILING,
    MAX_RADIUS_METERS,
    MIN_RADIUS_METERS,
)


# --------------------------------------------------------------------------- #
# Workspace settings (JSONB under ``workspace.settings["neighbor_outreach"]``)
# --------------------------------------------------------------------------- #
class NeighborOutreachSettings(BaseModel):
    """Validated per-workspace configuration for job-site neighbour outreach."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    # ~150 m is a block: the houses that actually watched the crew. Wider radii
    # stop being "neighbours who saw the work" and start being a mailing list.
    radius_meters: int = Field(
        default=DEFAULT_RADIUS_METERS,
        ge=MIN_RADIUS_METERS,
        le=MAX_RADIUS_METERS,
    )
    max_neighbors: int = Field(default=DEFAULT_MAX_NEIGHBORS, ge=1, le=MAX_NEIGHBORS_CEILING)
    # Generate the list automatically the moment a job flips to ``completed``.
    # Generation is read-only marketing prep — it never sends anything — so this
    # being on by default for an enabled workspace is safe.
    auto_generate_on_completion: bool = True
    # Saved :class:`app.models.message_template.MessageTemplate` used for the
    # messaging path. Reference only: messaging still requires a consented
    # contact, so setting a template can never by itself message a stranger.
    message_template_id: uuid.UUID | None = None
    # Master switch for the SMS/email path. Off by default: print/canvass is the
    # legal default channel, messaging is the opt-in exception.
    allow_messaging: bool = False


class NeighborOutreachSettingsUpdate(BaseModel):
    """Partial update payload for neighbour-outreach settings."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    radius_meters: int | None = Field(default=None, ge=MIN_RADIUS_METERS, le=MAX_RADIUS_METERS)
    max_neighbors: int | None = Field(default=None, ge=1, le=MAX_NEIGHBORS_CEILING)
    auto_generate_on_completion: bool | None = None
    message_template_id: uuid.UUID | None = None
    allow_messaging: bool | None = None


# --------------------------------------------------------------------------- #
# Runtime payloads
# --------------------------------------------------------------------------- #
class NeighborOutreachEntryResponse(BaseModel):
    """One neighbouring site in a job's outreach batch."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    service_location_id: uuid.UUID
    contact_id: int | None
    distance_meters: float
    status: NeighborOutreachStatus
    channel: NeighborOutreachChannel
    messaging_blocked_reason: str | None
    contacted_at: datetime | None
    status_changed_at: datetime | None
    notes: str | None
    created_at: datetime

    # Denormalized for the panel so it needs no second request. ``label`` is the
    # site's own name, never the address — the address only travels on the export.
    label: str | None = None
    customer_name: str | None = None
    # Whether this entry may be messaged at all (contact + consent + not opted
    # out). The UI uses it to disable the "message" affordance rather than letting
    # an operator queue a send the compliance layer will refuse.
    messageable: bool = False


class NeighborOutreachBatchResponse(BaseModel):
    """A job's generated neighbour list, nearest first."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_id: uuid.UUID
    origin_location_id: uuid.UUID | None
    origin_latitude: float
    origin_longitude: float
    radius_meters: int
    generated_at: datetime
    created_at: datetime

    entries: list[NeighborOutreachEntryResponse] = Field(default_factory=list)
    total: int = 0
    # How many entries are still ``pending``, and how many may legally be
    # messaged — the two numbers an operator acts on.
    pending_count: int = 0
    messageable_count: int = 0


class NeighborOutreachGenerateRequest(BaseModel):
    """Optional per-run overrides when generating a job's neighbour list."""

    model_config = ConfigDict(extra="forbid")

    radius_meters: int | None = Field(default=None, ge=MIN_RADIUS_METERS, le=MAX_RADIUS_METERS)
    max_neighbors: int | None = Field(default=None, ge=1, le=MAX_NEIGHBORS_CEILING)


class NeighborOutreachEntryUpdate(BaseModel):
    """Operator update for a single entry (status, channel, notes)."""

    model_config = ConfigDict(extra="forbid")

    status: NeighborOutreachStatus | None = None
    channel: NeighborOutreachChannel | None = None
    notes: str | None = Field(default=None, max_length=2000)


class NeighborOutreachExportRow(BaseModel):
    """One row of the door-hanger / direct-mail list.

    Carries the neighbour's postal address, which is customer PII decrypted out of
    :class:`app.models.field_service.ServiceLocation`. Dispatcher-gated, workspace
    scoped, and never persisted to a public path.
    """

    entry_id: uuid.UUID
    service_location_id: uuid.UUID
    label: str | None
    customer_name: str | None
    address_line1: str | None
    address_line2: str | None
    city: str | None
    state: str | None
    postal_code: str | None
    country: str
    latitude: float | None
    longitude: float | None
    distance_meters: float
    status: NeighborOutreachStatus
    channel: NeighborOutreachChannel


class NeighborOutreachExportResponse(BaseModel):
    """The exportable print/canvass list for a job's neighbour batch."""

    job_id: uuid.UUID
    batch_id: uuid.UUID
    radius_meters: int
    generated_at: datetime
    rows: list[NeighborOutreachExportRow] = Field(default_factory=list)
    total: int = 0


class NeighborOutreachCampaignRequest(BaseModel):
    """Enroll the *consented* subset of a batch into an existing campaign.

    Enrollment, not a bespoke sender: the entries become
    :class:`app.models.campaign.CampaignContact` rows on a campaign the operator
    already owns, so the send goes through the same pipeline — and the same
    :class:`app.services.compliance.OutboundComplianceService` gate at send time —
    as every other message the workspace sends. The eligibility filter here is an
    additional pre-flight check, not a replacement for it.
    """

    model_config = ConfigDict(extra="forbid")

    campaign_id: uuid.UUID
    channel: NeighborOutreachChannel = NeighborOutreachChannel.SMS


class NeighborOutreachCampaignResponse(BaseModel):
    """Outcome of an enrollment run over a batch.

    ``blocked_by_reason`` is the compliance ledger for the run: every entry that
    was *not* enrolled, grouped by why. An empty ``enrolled_entry_ids`` with a
    populated ``blocked_by_reason`` is the normal, correct result for a street of
    strangers — and the reason the default channel is print.
    """

    job_id: uuid.UUID
    batch_id: uuid.UUID
    campaign_id: uuid.UUID
    channel: NeighborOutreachChannel
    enrolled_entry_ids: list[uuid.UUID] = Field(default_factory=list)
    enrolled_count: int = 0
    skipped_count: int = 0
    blocked_by_reason: dict[str, int] = Field(default_factory=dict)
