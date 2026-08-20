"""Reusable HTML email template management endpoints.

Templates store structured blocks, not raw HTML — see
:mod:`app.models.email_template` for why. The preview endpoints render through
exactly the same code path as a real send, so what an operator approves is what
a customer receives.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import (
    DB,
    CanReadCRM,
    CanWriteOutreach,
    CurrentUser,
    require_route_capabilities,
)
from app.core.permissions import Capability
from app.db.scope import apply_workspace_scope
from app.models.email_template import EmailTemplate
from app.schemas.email_template import (
    EmailTemplateCreate,
    EmailTemplateDraftRequest,
    EmailTemplateListResponse,
    EmailTemplatePreviewRequest,
    EmailTemplatePreviewResponse,
    EmailTemplateResponse,
    EmailTemplateUpdate,
)
from app.services.email_templates import render_template

router = APIRouter(
    dependencies=[
        Depends(require_route_capabilities(Capability.CRM_READ, Capability.OUTREACH_WRITE))
    ]
)

# Stand-in opt-out link used only for previews. A marketing template refuses to
# render without one, and a preview must show the operator the footer their
# customers will see — but it must never be a live token for a real contact.
_PREVIEW_UNSUBSCRIBE_URL = "https://example.invalid/unsubscribe?preview=1"


async def _get_template(
    db: DB,
    workspace_id: uuid.UUID,
    template_id: uuid.UUID,
) -> EmailTemplate:
    """Fetch one workspace-scoped template or raise 404."""
    result = await db.execute(
        apply_workspace_scope(select(EmailTemplate), EmailTemplate, workspace_id).where(
            EmailTemplate.id == template_id
        )
    )
    template = result.scalar_one_or_none()
    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email template not found",
        )
    return template


@router.get("", response_model=EmailTemplateListResponse)
async def list_email_templates(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    _gate: CanReadCRM,
    active_only: bool = Query(default=False),
) -> EmailTemplateListResponse:
    """List a workspace's email templates, newest first."""
    query = apply_workspace_scope(select(EmailTemplate), EmailTemplate, workspace_id)
    count_query = apply_workspace_scope(
        select(func.count()).select_from(EmailTemplate), EmailTemplate, workspace_id
    )

    if active_only:
        query = query.where(EmailTemplate.is_active.is_(True))
        count_query = count_query.where(EmailTemplate.is_active.is_(True))

    result = await db.execute(query.order_by(EmailTemplate.created_at.desc()))
    total = (await db.execute(count_query)).scalar_one()

    return EmailTemplateListResponse(
        templates=[
            EmailTemplateResponse.model_validate(template) for template in result.scalars().all()
        ],
        total=total,
    )


@router.post("", response_model=EmailTemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_email_template(
    workspace_id: uuid.UUID,
    template_in: EmailTemplateCreate,
    current_user: CurrentUser,
    db: DB,
    _gate: CanWriteOutreach,
) -> EmailTemplate:
    """Create a template."""
    payload = template_in.model_dump(mode="json")
    template = EmailTemplate(workspace_id=workspace_id, **payload)
    db.add(template)
    try:
        await db.commit()
    except IntegrityError:
        # Names are unique per workspace so the builder's picker stays legible.
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A template named '{template_in.name}' already exists",
        ) from None
    await db.refresh(template)
    return template


@router.get("/{template_id}", response_model=EmailTemplateResponse)
async def get_email_template(
    workspace_id: uuid.UUID,
    template_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    _gate: CanReadCRM,
) -> EmailTemplate:
    """Get one template."""
    return await _get_template(db, workspace_id, template_id)


@router.put("/{template_id}", response_model=EmailTemplateResponse)
async def update_email_template(
    workspace_id: uuid.UUID,
    template_id: uuid.UUID,
    template_in: EmailTemplateUpdate,
    current_user: CurrentUser,
    db: DB,
    _gate: CanWriteOutreach,
) -> EmailTemplate:
    """Update a template. Unset fields are left untouched."""
    template = await _get_template(db, workspace_id, template_id)

    for field, value in template_in.model_dump(mode="json", exclude_unset=True).items():
        setattr(template, field, value)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A template with that name already exists",
        ) from None
    await db.refresh(template)
    return template


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_email_template(
    workspace_id: uuid.UUID,
    template_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    _gate: CanWriteOutreach,
) -> None:
    """Delete a template."""
    template = await _get_template(db, workspace_id, template_id)
    await db.delete(template)
    await db.commit()


@router.post("/{template_id}/preview", response_model=EmailTemplatePreviewResponse)
async def preview_email_template(
    workspace_id: uuid.UUID,
    template_id: uuid.UUID,
    preview_in: EmailTemplatePreviewRequest,
    current_user: CurrentUser,
    db: DB,
    _gate: CanReadCRM,
) -> EmailTemplatePreviewResponse:
    """Render a saved template with sample values. Sends nothing."""
    template = await _get_template(db, workspace_id, template_id)
    return _render_preview(
        subject=template.subject,
        heading=template.heading,
        preheader=template.preheader,
        blocks=template.blocks,
        category=template.category,
        sample_values=preview_in.sample_values,
    )


@router.post("/preview-draft", response_model=EmailTemplatePreviewResponse)
async def preview_email_draft(
    workspace_id: uuid.UUID,
    draft_in: EmailTemplateDraftRequest,
    current_user: CurrentUser,
    db: DB,
    _gate: CanReadCRM,
) -> EmailTemplatePreviewResponse:
    """Render unsaved blocks — powers live preview while authoring."""
    return _render_preview(
        subject=draft_in.subject,
        heading=draft_in.heading,
        preheader=draft_in.preheader,
        blocks=[block.model_dump(mode="json") for block in draft_in.blocks],
        category=draft_in.category,
        sample_values=draft_in.sample_values,
    )


def _render_preview(
    *,
    subject: str,
    heading: str | None,
    preheader: str | None,
    blocks: list[dict[str, Any]] | None,
    category: str,
    sample_values: dict[str, str],
) -> EmailTemplatePreviewResponse:
    """Shared preview rendering for saved and draft templates."""
    is_marketing = category == "marketing"
    try:
        rendered_subject, rendered = render_template(
            subject=subject,
            heading=heading,
            preheader=preheader,
            blocks=blocks,
            category=category,
            values=sample_values,
            unsubscribe_url=_PREVIEW_UNSUBSCRIBE_URL if is_marketing else None,
        )
    except ValueError as exc:
        # Surfaced as 422 so the builder can show the authoring problem inline
        # rather than the operator meeting it at send time.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    return EmailTemplatePreviewResponse(
        subject=rendered_subject,
        html=rendered.html,
        text=rendered.text,
        includes_unsubscribe=is_marketing,
    )
