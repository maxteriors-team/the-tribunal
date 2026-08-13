"""Schemas for reusable HTML email templates.

Blocks are a discriminated union rather than free-form JSON so an operator can
only author shapes the renderer actually understands. A template that stores
``{"type": "buton"}`` would otherwise save cleanly and then silently render
nothing at send time — a mistake the operator would discover from a customer.
"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Mirrors app.services.email_layout.EmailCategory. Marketing carries an
# unsubscribe footer and skips opted-out contacts; transactional does neither.
EMAIL_TEMPLATE_CATEGORIES: tuple[str, ...] = ("transactional", "marketing")
_CATEGORY_PATTERN = "^(" + "|".join(EMAIL_TEMPLATE_CATEGORIES) + ")$"

CALLOUT_TONES: tuple[str, ...] = ("neutral", "success", "warning", "destructive")


class ParagraphBlockSchema(BaseModel):
    """A run of copy. Placeholders supported; escaped and linkified on render."""

    type: Literal["paragraph"]
    text: str = Field(..., min_length=1, max_length=5000)
    muted: bool = False


class DetailsBlockSchema(BaseModel):
    """Label/value rows — appointment facts, quote lines, job details."""

    type: Literal["details"]
    rows: dict[str, str] = Field(default_factory=dict, max_length=25)


class ButtonBlockSchema(BaseModel):
    """A single call to action.

    ``url`` is not pattern-validated here because it may contain placeholders
    (``{booking_url}``) that are substituted at send time; the renderer refuses
    any non-HTTP scheme after substitution, which is where the real check has
    to live.
    """

    type: Literal["button"]
    label: str = Field(..., min_length=1, max_length=120)
    url: str = Field(..., min_length=1, max_length=2048)


class CalloutBlockSchema(BaseModel):
    """A tinted panel for the one thing that matters (a total, a code)."""

    type: Literal["callout"]
    text: str = Field(..., min_length=1, max_length=1000)
    tone: Literal["neutral", "success", "warning", "destructive"] = "neutral"


class DividerBlockSchema(BaseModel):
    """A horizontal rule."""

    type: Literal["divider"]


EmailBlockSchema = Annotated[
    ParagraphBlockSchema
    | DetailsBlockSchema
    | ButtonBlockSchema
    | CalloutBlockSchema
    | DividerBlockSchema,
    Field(discriminator="type"),
]


class EmailTemplateBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    subject: str = Field(..., min_length=1, max_length=500)
    heading: str | None = Field(default=None, max_length=500)
    preheader: str | None = Field(default=None, max_length=500)
    blocks: list[EmailBlockSchema] = Field(default_factory=list, max_length=50)
    category: str = Field(default="marketing", pattern=_CATEGORY_PATTERN)
    is_active: bool = True


class EmailTemplateCreate(EmailTemplateBase):
    """Payload for creating a template."""


class EmailTemplateUpdate(BaseModel):
    """Partial update. Unset fields are left untouched."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    subject: str | None = Field(default=None, min_length=1, max_length=500)
    heading: str | None = Field(default=None, max_length=500)
    preheader: str | None = Field(default=None, max_length=500)
    blocks: list[EmailBlockSchema] | None = Field(default=None, max_length=50)
    category: str | None = Field(default=None, pattern=_CATEGORY_PATTERN)
    is_active: bool | None = None


class EmailTemplateResponse(EmailTemplateBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    created_at: datetime
    updated_at: datetime


class EmailTemplatePreviewRequest(BaseModel):
    """Render a template with sample values without sending anything."""

    # Placeholder values to substitute, e.g. {"first_name": "Ada"}. Missing
    # tokens are left visible so the operator can see what did not resolve.
    sample_values: dict[str, str] = Field(default_factory=dict, max_length=50)


class EmailTemplatePreviewResponse(BaseModel):
    """Both rendered parts, so the operator can check the text fallback too."""

    subject: str
    html: str
    text: str
    # True when the preview included an unsubscribe footer (marketing only).
    includes_unsubscribe: bool


class EmailTemplateDraftRequest(BaseModel):
    """Ad-hoc render of unsaved blocks — powers live preview while authoring."""

    subject: str = Field(..., min_length=1, max_length=500)
    heading: str | None = Field(default=None, max_length=500)
    preheader: str | None = Field(default=None, max_length=500)
    blocks: list[EmailBlockSchema] = Field(default_factory=list, max_length=50)
    category: str = Field(default="marketing", pattern=_CATEGORY_PATTERN)
    sample_values: dict[str, str] = Field(default_factory=dict, max_length=50)


class EmailTemplateListResponse(BaseModel):
    templates: list[EmailTemplateResponse]
    total: int


__all__ = [
    "CALLOUT_TONES",
    "EMAIL_TEMPLATE_CATEGORIES",
    "ButtonBlockSchema",
    "CalloutBlockSchema",
    "DetailsBlockSchema",
    "DividerBlockSchema",
    "EmailBlockSchema",
    "EmailTemplateCreate",
    "EmailTemplateDraftRequest",
    "EmailTemplateListResponse",
    "EmailTemplatePreviewRequest",
    "EmailTemplatePreviewResponse",
    "EmailTemplateResponse",
    "EmailTemplateUpdate",
    "ParagraphBlockSchema",
]
