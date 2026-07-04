"""CompanyCam contact-photos endpoint.

Read-only surface: given a contact, find their CompanyCam projects (matched by
name/phone/email/address — see ``find_projects_for_contact``) and return recent
photo thumbnails plus deep links into CompanyCam. Photos stay in CompanyCam;
nothing is persisted here.
"""

import asyncio
import uuid
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import DB, WorkspaceAccess
from app.models.contact import Contact
from app.models.workspace import WorkspaceIntegration
from app.schemas.companycam import (
    CompanyCamPhoto,
    CompanyCamProjectPhotos,
    ContactCompanyCamPhotosResponse,
)
from app.services.companycam import (
    CompanyCamApiError,
    CompanyCamClient,
    find_projects_for_contact,
)
from app.services.companycam.client import MAX_PHOTOS_PER_PROJECT

router = APIRouter()
logger = structlog.get_logger()


def _photo_urls(photo: dict[str, Any]) -> tuple[str, str]:
    """Pick (thumbnail, web) URLs from a photo's ``uris`` list."""
    by_type = {
        entry.get("type"): entry.get("url") or entry.get("uri")
        for entry in photo.get("uris") or []
        if isinstance(entry, dict)
    }
    web = by_type.get("web") or by_type.get("original") or ""
    thumbnail = by_type.get("thumbnail") or web
    return thumbnail or "", web or ""


def _format_address(project: dict[str, Any]) -> str | None:
    address = project.get("address") or {}
    if not isinstance(address, dict):
        return None
    parts = [
        address.get("street_address_1"),
        address.get("city"),
        address.get("state"),
    ]
    formatted = ", ".join(p for p in parts if p)
    return formatted or None


@router.get(
    "/contacts/{contact_id}/companycam-photos",
    response_model=ContactCompanyCamPhotosResponse,
)
async def get_contact_companycam_photos(
    workspace_id: uuid.UUID,
    contact_id: int,
    workspace: WorkspaceAccess,
    db: DB,
) -> ContactCompanyCamPhotosResponse:
    """Return CompanyCam projects + recent photos matched to a contact."""
    integration = (
        await db.execute(
            select(WorkspaceIntegration).where(
                WorkspaceIntegration.workspace_id == workspace.id,
                WorkspaceIntegration.integration_type == "companycam",
                WorkspaceIntegration.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if integration is None:
        return ContactCompanyCamPhotosResponse(connected=False, projects=[])

    access_token = integration.credentials.get("api_key", "")
    if not access_token:
        return ContactCompanyCamPhotosResponse(connected=False, projects=[])

    contact = (
        await db.execute(
            select(Contact).where(
                Contact.id == contact_id,
                Contact.workspace_id == workspace.id,
            )
        )
    ).scalar_one_or_none()
    if contact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found")

    client = CompanyCamClient(access_token)
    try:
        projects = await find_projects_for_contact(
            client,
            first_name=contact.first_name,
            last_name=contact.last_name,
            phone_number=contact.phone_number,
            email=contact.email,
            address_line1=contact.address_line1,
        )
        photo_lists = await asyncio.gather(
            *(
                client.list_project_photos(str(p["id"]), per_page=MAX_PHOTOS_PER_PROJECT)
                for p in projects
            )
        )
    except CompanyCamApiError as exc:
        logger.warning(
            "companycam_lookup_failed",
            workspace_id=str(workspace.id),
            contact_id=contact_id,
            status_code=exc.status_code,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="CompanyCam request failed — check the integration token.",
        ) from exc

    project_payloads: list[CompanyCamProjectPhotos] = []
    for project, photos in zip(projects, photo_lists, strict=True):
        photo_payloads = []
        for photo in photos:
            thumbnail, web = _photo_urls(photo)
            if not thumbnail:
                continue
            photo_payloads.append(
                CompanyCamPhoto(
                    id=str(photo.get("id") or ""),
                    thumbnail_url=thumbnail,
                    web_url=web,
                    captured_at=photo.get("captured_at"),
                    creator_name=photo.get("creator_name"),
                )
            )
        project_payloads.append(
            CompanyCamProjectPhotos(
                project_id=str(project.get("id") or ""),
                project_name=project.get("name") or "Untitled project",
                project_url=project.get("project_url") or "",
                photo_count=int(project.get("photo_count") or 0),
                address=_format_address(project),
                photos=photo_payloads,
            )
        )

    return ContactCompanyCamPhotosResponse(connected=True, projects=project_payloads)
