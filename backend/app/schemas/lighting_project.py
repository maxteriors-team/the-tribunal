"""Strict API contracts for workspace-scoped landscape-lighting projects."""

from __future__ import annotations

import json
import math
from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)
from pydantic.alias_generators import to_camel

MAX_LANDSCAPE_DOCUMENT_BYTES = 20 * 1024 * 1024
MAX_LANDSCAPE_SHOTS = 6
MAX_PLAN_IMAGES_PER_SHOT = 12
MAX_DATA_URL_CHARS = 8 * 1024 * 1024

DocumentText = Annotated[str, StringConstraints(max_length=2000)]
ShortText = Annotated[str, StringConstraints(max_length=250)]
CatalogKey = Annotated[str, StringConstraints(max_length=160)]


class ApiSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class DocumentSchema(ApiSchema):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, alias_generator=to_camel)


class PointSchema(DocumentSchema):
    x: float
    y: float

    @field_validator("x", "y")
    @classmethod
    def finite_coordinates(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("coordinates must be finite")
        return value


class CalibrationSchema(DocumentSchema):
    a: PointSchema
    b: PointSchema
    feet: Annotated[float, Field(gt=0, le=100_000)]


class RunSchema(DocumentSchema):
    id: ShortText
    product_id: ShortText = Field(validation_alias=AliasChoices("productId", "product_id"))
    points: Annotated[list[PointSchema], Field(max_length=5000)]
    # Which of the drawing's two scales measured this run. Missing means scale 1.
    scale_slot: Literal[1, 2] | None = Field(
        default=None, validation_alias=AliasChoices("scaleSlot", "scale_slot")
    )
    # Per-run install difficulty; weights permanent-lighting markup at quote time.
    permanent_complexity: Literal["aerial", "easy", "standard", "complex"] | None = Field(
        default=None,
        validation_alias=AliasChoices("permanentComplexity", "permanent_complexity"),
    )
    spacing_in: Annotated[float, Field(gt=0, le=1200)] | None = Field(
        default=None, validation_alias=AliasChoices("spacingIn", "spacing_in")
    )
    colors: Annotated[list[ShortText], Field(max_length=24)] | None = None
    bulb_scale: Annotated[float, Field(gt=0, le=10)] | None = Field(
        default=None, validation_alias=AliasChoices("bulbScale", "bulb_scale")
    )
    circuit_label: ShortText | None = Field(
        default=None, validation_alias=AliasChoices("circuitLabel", "circuit_label")
    )
    transformer_id: ShortText | None = Field(
        default=None, validation_alias=AliasChoices("transformerId", "transformer_id")
    )
    wire_gauge: Literal[8, 10, 12, 14] | None = Field(
        default=None, validation_alias=AliasChoices("wireGauge", "wire_gauge")
    )
    source_voltage: Annotated[float, Field(ge=10, le=24)] | None = Field(
        default=None, validation_alias=AliasChoices("sourceVoltage", "source_voltage")
    )
    transformer_zone_id: ShortText | None = Field(
        default=None,
        validation_alias=AliasChoices("transformerZoneId", "transformer_zone_id"),
    )


class PlacedItemSchema(DocumentSchema):
    id: ShortText
    product_id: ShortText = Field(validation_alias=AliasChoices("productId", "product_id"))
    at: PointSchema
    size_px: Annotated[float, Field(gt=0, le=10_000)] = Field(
        validation_alias=AliasChoices("sizePx", "size_px")
    )
    icon_scale: Annotated[float, Field(ge=0.6, le=1.8)] | None = Field(
        default=None, validation_alias=AliasChoices("iconScale", "icon_scale")
    )
    beam_angle_deg: Annotated[float, Field(ge=1, le=179)] | None = Field(
        default=None, validation_alias=AliasChoices("beamAngleDeg", "beam_angle_deg")
    )
    beam_rotation_deg: Annotated[float, Field(ge=-3600, le=3600)] | None = Field(
        default=None,
        validation_alias=AliasChoices("beamRotationDeg", "beam_rotation_deg"),
    )
    circuit_id: ShortText | None = Field(
        default=None, validation_alias=AliasChoices("circuitId", "circuit_id")
    )
    bistro_run_id: ShortText | None = Field(
        default=None, validation_alias=AliasChoices("bistroRunId", "bistro_run_id")
    )
    marker_color: Annotated[str, StringConstraints(pattern=r"^#[0-9A-Fa-f]{6}$")] | None = Field(
        default=None, validation_alias=AliasChoices("markerColor", "marker_color")
    )
    catalog_item_id: CatalogKey | None = Field(
        default=None, validation_alias=AliasChoices("catalogItemId", "catalog_item_id")
    )
    # True when the rep pinned this exact catalog product instead of letting the
    # package default substitute one.
    catalog_item_override: bool | None = Field(
        default=None,
        validation_alias=AliasChoices("catalogItemOverride", "catalog_item_override"),
    )
    catalog_sku: CatalogKey | None = Field(
        default=None, validation_alias=AliasChoices("catalogSku", "catalog_sku")
    )
    lamp_catalog_item_id: CatalogKey | None = Field(
        default=None,
        validation_alias=AliasChoices("lampCatalogItemId", "lamp_catalog_item_id"),
    )
    accessory_catalog_item_ids: Annotated[list[CatalogKey], Field(max_length=24)] | None = Field(
        default=None,
        validation_alias=AliasChoices("accessoryCatalogItemIds", "accessory_catalog_item_ids"),
    )
    transformer_zone_id: ShortText | None = Field(
        default=None,
        validation_alias=AliasChoices("transformerZoneId", "transformer_zone_id"),
    )


class PlanImageSchema(DocumentSchema):
    id: ShortText
    data_url: str = Field(validation_alias=AliasChoices("dataUrl", "data_url"))
    name: ShortText
    at: PointSchema
    width_px: Annotated[float, Field(gt=0, le=100_000)] = Field(
        validation_alias=AliasChoices("widthPx", "width_px")
    )
    height_px: Annotated[float, Field(gt=0, le=100_000)] = Field(
        validation_alias=AliasChoices("heightPx", "height_px")
    )

    @field_validator("data_url")
    @classmethod
    def embedded_image_only(cls, value: str) -> str:
        if not value.startswith("data:image/") or len(value) > MAX_DATA_URL_CHARS:
            raise ValueError("plan image must be an embedded image data URL")
        return value


class RevisionRowSchema(DocumentSchema):
    id: ShortText
    number: ShortText = ""
    description: DocumentText = ""
    date: str = ""
    author: ShortText = ""


class AnnotationSchema(DocumentSchema):
    id: ShortText
    type: Literal["note", "line", "tree", "photo", "revision"]
    at: PointSchema
    end: PointSchema | None = None
    text: DocumentText | None = None
    size_px: Annotated[float, Field(gt=0, le=10_000)] | None = Field(
        default=None, validation_alias=AliasChoices("sizePx", "size_px")
    )
    rotation_deg: Annotated[float, Field(ge=-3600, le=3600)] | None = Field(
        default=None, validation_alias=AliasChoices("rotationDeg", "rotation_deg")
    )
    image_data_url: str | None = Field(
        default=None, validation_alias=AliasChoices("imageDataUrl", "image_data_url")
    )

    @field_validator("image_data_url")
    @classmethod
    def valid_optional_image(cls, value: str | None) -> str | None:
        if value is not None and (
            not value.startswith("data:image/") or len(value) > MAX_DATA_URL_CHARS
        ):
            raise ValueError("annotation image must be an embedded image data URL")
        return value


class MeasurementSchema(DocumentSchema):
    id: ShortText
    a: PointSchema
    b: PointSchema
    label: ShortText | None = None
    visible: bool | None = None


class HighlightSchema(DocumentSchema):
    id: ShortText
    points: Annotated[list[PointSchema], Field(min_length=2, max_length=5000)]
    color: Annotated[str, StringConstraints(pattern=r"^#[0-9A-Fa-f]{6}$")]
    width_px: Annotated[float, Field(gt=0, le=500)] = Field(
        validation_alias=AliasChoices("widthPx", "width_px")
    )


class ArrowSchema(DocumentSchema):
    id: ShortText
    a: PointSchema
    b: PointSchema
    label: ShortText | None = None


class DesignSchema(DocumentSchema):
    calibration: CalibrationSchema | None = None
    runs: Annotated[list[RunSchema], Field(max_length=5000)] = Field(default_factory=list)
    items: Annotated[list[PlacedItemSchema], Field(max_length=5000)] = Field(default_factory=list)
    plan_images: Annotated[list[PlanImageSchema], Field(max_length=MAX_PLAN_IMAGES_PER_SHOT)] = (
        Field(default_factory=list, validation_alias=AliasChoices("planImages", "plan_images"))
    )
    annotations: Annotated[list[AnnotationSchema], Field(max_length=2000)] = Field(
        default_factory=list
    )
    measurements: Annotated[list[MeasurementSchema], Field(max_length=2000)] = Field(
        default_factory=list
    )
    highlights: Annotated[list[HighlightSchema], Field(max_length=1000)] = Field(
        default_factory=list
    )
    arrows: Annotated[list[ArrowSchema], Field(max_length=2000)] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_ids_and_references(self) -> DesignSchema:
        groups = {
            "run": [entry.id for entry in self.runs],
            "item": [entry.id for entry in self.items],
            "plan image": [entry.id for entry in self.plan_images],
            "annotation": [entry.id for entry in self.annotations],
            "measurement": [entry.id for entry in self.measurements],
            "highlight": [entry.id for entry in self.highlights],
            "arrow": [entry.id for entry in self.arrows],
        }
        for label, ids in groups.items():
            if len(ids) != len(set(ids)):
                raise ValueError(f"{label} IDs must be unique")
        run_ids = {run.id for run in self.runs}
        item_ids = {item.id for item in self.items}
        if any(item.circuit_id and item.circuit_id not in run_ids for item in self.items):
            raise ValueError("fixture circuitId must reference a wire run")
        if any(run.transformer_id and run.transformer_id not in item_ids for run in self.runs):
            raise ValueError("run transformerId must reference a placed item")
        return self


class SheetMetadataSchema(DocumentSchema):
    label: ShortText | None = None
    drawing_title: ShortText | None = Field(
        default=None, validation_alias=AliasChoices("drawingTitle", "drawing_title")
    )
    drawing_number: ShortText | None = Field(
        default=None, validation_alias=AliasChoices("drawingNumber", "drawing_number")
    )
    proposal_zone_id: ShortText | None = Field(
        default=None, validation_alias=AliasChoices("proposalZoneId", "proposal_zone_id")
    )
    revisions: Annotated[list[RevisionRowSchema], Field(max_length=100)] = Field(
        default_factory=list
    )


class PhotoSchema(DocumentSchema):
    data_url: str = Field(validation_alias=AliasChoices("dataUrl", "data_url"))
    width: Annotated[int, Field(gt=0, le=100_000)]
    height: Annotated[int, Field(gt=0, le=100_000)]

    @field_validator("data_url")
    @classmethod
    def embedded_photo_only(cls, value: str) -> str:
        if not value.startswith("data:image/") or len(value) > MAX_DATA_URL_CHARS:
            raise ValueError("photo must be an embedded image data URL")
        return value


class LandscapeShotSchema(DocumentSchema):
    id: ShortText
    photo: PhotoSchema
    design: DesignSchema
    dusk: Annotated[float, Field(ge=0, le=1)]
    sheet: SheetMetadataSchema | None = None


class LegendSettingsSchema(DocumentSchema):
    visible: bool = True
    position: PointSchema = Field(default_factory=lambda: PointSchema(x=24, y=24))
    scale: Annotated[float, Field(ge=0.5, le=2)] = 1


class DocumentSettingsSchema(DocumentSchema):
    paper_size: Literal["tabloid", "super-b", "letter", "arch-c", "arch-d", "ansi-d"] = Field(
        default="tabloid", validation_alias=AliasChoices("paperSize", "paper_size")
    )
    plan_fit: Literal["contain", "cover"] = Field(
        default="contain", validation_alias=AliasChoices("planFit", "plan_fit")
    )
    plan_opacity: Annotated[float, Field(ge=0.1, le=1)] = Field(
        default=1, validation_alias=AliasChoices("planOpacity", "plan_opacity")
    )
    legend: LegendSettingsSchema = Field(default_factory=LegendSettingsSchema)
    halos_visible: bool = Field(
        default=True, validation_alias=AliasChoices("halosVisible", "halos_visible")
    )
    fixture_numbers_visible: bool = Field(
        default=True,
        validation_alias=AliasChoices("fixtureNumbersVisible", "fixture_numbers_visible"),
    )
    measurements_visible: bool = Field(
        default=True,
        validation_alias=AliasChoices("measurementsVisible", "measurements_visible"),
    )
    source_voltage: Annotated[float, Field(ge=10, le=24)] = Field(
        default=13, validation_alias=AliasChoices("sourceVoltage", "source_voltage")
    )


class ProposalZoneSchema(DocumentSchema):
    id: ShortText
    name: ShortText
    description: DocumentText = ""
    shot_ids: Annotated[list[ShortText], Field(max_length=MAX_LANDSCAPE_SHOTS)] = Field(
        default_factory=list, validation_alias=AliasChoices("shotIds", "shot_ids")
    )


class PaymentMilestoneSchema(DocumentSchema):
    id: ShortText
    label: ShortText
    percent: Annotated[float, Field(ge=0, le=100)]


class ProposalEnhancementSchema(DocumentSchema):
    id: ShortText
    catalog_item_id: CatalogKey = Field(
        validation_alias=AliasChoices("catalogItemId", "catalog_item_id")
    )
    catalog_sku: CatalogKey | None = Field(
        default=None, validation_alias=AliasChoices("catalogSku", "catalog_sku")
    )
    quantity: Annotated[float, Field(gt=0, le=100_000)]
    note: DocumentText = ""


class ProposalLineItemSchema(DocumentSchema):
    id: ShortText
    description: Annotated[str, Field(max_length=500)] = ""
    amount: Annotated[float, Field(ge=0, le=1_000_000)] = 0


class ProposalDraftSchema(DocumentSchema):
    selected_tier_key: ShortText | None = Field(
        default=None, validation_alias=AliasChoices("selectedTierKey", "selected_tier_key")
    )
    selected_care_plan_key: ShortText | None = Field(
        default=None,
        validation_alias=AliasChoices("selectedCarePlanKey", "selected_care_plan_key"),
    )
    design_intent: DocumentText = Field(
        default="", validation_alias=AliasChoices("designIntent", "design_intent")
    )
    show_combined_total: bool = Field(
        default=True,
        validation_alias=AliasChoices("showCombinedTotal", "show_combined_total"),
    )
    show_fixture_details: bool = Field(
        default=True,
        validation_alias=AliasChoices("showFixtureDetails", "show_fixture_details"),
    )
    zones: Annotated[list[ProposalZoneSchema], Field(max_length=100)] = Field(default_factory=list)
    payment_milestones: Annotated[list[PaymentMilestoneSchema], Field(max_length=20)] = Field(
        default_factory=list,
        validation_alias=AliasChoices("paymentMilestones", "payment_milestones"),
    )
    electrical_responsibility: DocumentText = Field(
        default="",
        validation_alias=AliasChoices("electricalResponsibility", "electrical_responsibility"),
    )
    enhancements: Annotated[list[ProposalEnhancementSchema], Field(max_length=100)] = Field(
        default_factory=list
    )
    additional_line_items: Annotated[list[ProposalLineItemSchema], Field(max_length=100)] = Field(
        default_factory=list,
        validation_alias=AliasChoices("additionalLineItems", "additional_line_items"),
    )
    commitments: Annotated[list[DocumentText], Field(max_length=100)] = Field(default_factory=list)
    signature_name: ShortText = Field(
        default="", validation_alias=AliasChoices("signatureName", "signature_name")
    )
    signature_date: date | None = Field(
        default=None, validation_alias=AliasChoices("signatureDate", "signature_date")
    )


class BomLineItemSchema(DocumentSchema):
    id: ShortText
    description: Annotated[str, Field(max_length=500)] = ""
    sku: CatalogKey = ""
    quantity: Annotated[float, Field(ge=0, le=100_000)] = 1
    unit: Literal["each", "ft"] = "each"


class ProcurementStateSchema(DocumentSchema):
    catalog_item_id: CatalogKey | None = Field(
        default=None, validation_alias=AliasChoices("catalogItemId", "catalog_item_id")
    )
    catalog_sku: CatalogKey | None = Field(
        default=None, validation_alias=AliasChoices("catalogSku", "catalog_sku")
    )
    description: DocumentText | None = None
    manufacturer: ShortText | None = None
    supplier: ShortText | None = None
    needed_quantity: Annotated[float, Field(ge=0, le=100_000)] | None = Field(
        default=None, validation_alias=AliasChoices("neededQuantity", "needed_quantity")
    )
    ordered_quantity: Annotated[float, Field(ge=0, le=100_000)] = Field(
        default=0, validation_alias=AliasChoices("orderedQuantity", "ordered_quantity")
    )
    received_quantity: Annotated[float, Field(ge=0, le=100_000)] = Field(
        default=0, validation_alias=AliasChoices("receivedQuantity", "received_quantity")
    )
    unit_cost: Annotated[float, Field(ge=0, le=1_000_000)] | None = Field(
        default=None, validation_alias=AliasChoices("unitCost", "unit_cost")
    )
    supplier_note: DocumentText = Field(
        default="", validation_alias=AliasChoices("supplierNote", "supplier_note")
    )


class PreconResponseSchema(DocumentSchema):
    item_id: ShortText = Field(validation_alias=AliasChoices("itemId", "item_id"))
    value: Literal["yes", "no", "na"] | None = None
    comment: DocumentText = ""


class PreconStateSchema(DocumentSchema):
    responses: Annotated[list[PreconResponseSchema], Field(max_length=26)] = Field(
        default_factory=list
    )
    lead_installer: ShortText = Field(
        default="", validation_alias=AliasChoices("leadInstaller", "lead_installer")
    )
    notes: DocumentText = ""

    @model_validator(mode="after")
    def unique_responses(self) -> PreconStateSchema:
        ids = [response.item_id for response in self.responses]
        if len(ids) != len(set(ids)):
            raise ValueError("pre-con responses must use unique item IDs")
        return self


class LandscapeDraftDocument(DocumentSchema):
    version: Literal[2] = 2
    project_type: Literal["landscape", "permanent"] = Field(
        default="landscape",
        validation_alias=AliasChoices("projectType", "project_type"),
    )
    active_shot_id: ShortText | None = Field(
        default=None, validation_alias=AliasChoices("activeShotId", "active_shot_id")
    )
    active_workflow_tab: (
        Literal["drawing", "schedule", "bom", "electrical", "proposal", "precon"] | None
    ) = Field(
        default=None,
        validation_alias=AliasChoices("activeWorkflowTab", "active_workflow_tab"),
    )
    shots: Annotated[list[LandscapeShotSchema], Field(max_length=MAX_LANDSCAPE_SHOTS)] = Field(
        default_factory=list
    )
    updated_at: datetime = Field(
        default_factory=datetime.now,
        validation_alias=AliasChoices("updatedAt", "updated_at"),
    )
    settings: DocumentSettingsSchema = Field(default_factory=DocumentSettingsSchema)
    proposal: ProposalDraftSchema = Field(default_factory=ProposalDraftSchema)
    bom_line_items: Annotated[list[BomLineItemSchema], Field(max_length=100)] = Field(
        default_factory=list, validation_alias=AliasChoices("bomLineItems", "bom_line_items")
    )
    procurement: dict[ShortText, ProcurementStateSchema] = Field(default_factory=dict)
    precon: PreconStateSchema = Field(default_factory=PreconStateSchema)

    @model_validator(mode="after")
    def validate_document(self) -> LandscapeDraftDocument:
        shot_ids = [shot.id for shot in self.shots]
        if len(shot_ids) != len(set(shot_ids)):
            raise ValueError("shot IDs must be unique")
        if self.active_shot_id is not None and self.active_shot_id not in set(shot_ids):
            raise ValueError("activeShotId must reference a saved shot")
        bom_line_ids = [line.id for line in self.bom_line_items]
        if len(bom_line_ids) != len(set(bom_line_ids)):
            raise ValueError("BOM line items must use unique IDs")
        for zone in self.proposal.zones:
            if any(shot_id not in set(shot_ids) for shot_id in zone.shot_ids):
                raise ValueError("proposal zone shotIds must reference saved shots")
        serialized = json.dumps(self.model_dump(mode="json", by_alias=True), separators=(",", ":"))
        if len(serialized.encode("utf-8")) > MAX_LANDSCAPE_DOCUMENT_BYTES:
            raise ValueError("landscape project document exceeds the allowed size")
        return self

    def with_server_timestamp(self, value: datetime) -> LandscapeDraftDocument:
        return self.model_copy(update={"updated_at": value})


def empty_landscape_document(
    now: datetime, project_type: Literal["landscape", "permanent"] = "landscape"
) -> LandscapeDraftDocument:
    return LandscapeDraftDocument(updated_at=now, project_type=project_type)


LightingProjectStatus = Literal["active", "archived"]
LightingProjectType = Literal["landscape", "permanent"]


class LightingProjectSummary(ApiSchema):
    id: UUID
    workspace_id: UUID
    contact_id: int
    contact_name: str
    service_location_id: UUID | None
    opportunity_id: UUID | None
    assigned_user_id: int | None
    name: str
    project_type: LightingProjectType
    status: LightingProjectStatus
    version: int
    installation_shot_id: ShortText | None
    updated_by_id: int | None
    updater_name: str | None
    created_at: datetime
    updated_at: datetime


class LightingProjectRevision(ApiSchema):
    version: Annotated[int, Field(ge=1)]


class LightingProjectDetail(LightingProjectSummary):
    document: LandscapeDraftDocument
    created_by_id: int | None


class PaginatedLightingProjects(ApiSchema):
    items: list[LightingProjectSummary]
    total: int
    page: int
    page_size: int
    pages: int


class LightingProjectCreate(ApiSchema):
    contact_id: int
    service_location_id: UUID | None = None
    opportunity_id: UUID | None = None
    assigned_user_id: int | None = None
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    project_type: LightingProjectType = "landscape"
    document: LandscapeDraftDocument | None = None
    installation_shot_id: ShortText | None = None

    @model_validator(mode="after")
    def validate_document_links(self) -> LightingProjectCreate:
        if self.document is not None and self.document.project_type != self.project_type:
            raise ValueError("document projectType must match project_type")
        if self.installation_shot_id is not None:
            document = self.document
            if document is None or self.installation_shot_id not in {
                shot.id for shot in document.shots
            }:
                raise ValueError("installation_shot_id must reference a saved shot")
        return self


class LightingProjectUpdate(ApiSchema):
    expected_version: Annotated[int, Field(ge=1)]
    name: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
        | None
    ) = None
    status: LightingProjectStatus | None = None
    service_location_id: UUID | None = None
    opportunity_id: UUID | None = None
    assigned_user_id: int | None = None
    document: LandscapeDraftDocument | None = None
    installation_shot_id: ShortText | None = None

    @model_validator(mode="before")
    @classmethod
    def require_non_null_change(cls, value: object) -> object:
        if isinstance(value, dict):
            changed = {
                key: item
                for key, item in value.items()
                if key != "expected_version" and item is not None
            }
            if not changed:
                raise ValueError("at least one non-null project field is required")
        return value

    @model_validator(mode="after")
    def selected_shot_exists_in_submitted_document(self) -> LightingProjectUpdate:
        if (
            self.installation_shot_id is not None
            and self.document is not None
            and self.installation_shot_id not in {shot.id for shot in self.document.shots}
        ):
            raise ValueError("installation_shot_id must reference a saved shot")
        return self
