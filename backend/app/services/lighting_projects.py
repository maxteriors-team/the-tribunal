"""Tenant-safe persistence and optimistic concurrency for lighting projects."""

import uuid
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.pagination import paginate
from app.db.scope import assert_workspace_owned
from app.models.contact import Contact
from app.models.field_service import ServiceLocation
from app.models.lighting_project import LightingProject
from app.models.opportunity import Opportunity, opportunity_contact_table
from app.models.user import User
from app.schemas.lighting_project import (
    LandscapeDraftDocument,
    LightingProjectCreate,
    LightingProjectDetail,
    LightingProjectStatus,
    LightingProjectSummary,
    LightingProjectType,
    LightingProjectUpdate,
    PaginatedLightingProjects,
    empty_landscape_document,
)
from app.services.exceptions import ConflictError, NotFoundError, ValidationError
from app.services.workspaces.membership import assert_active_workspace_member


class LightingProjectService:
    """Manage one workspace's versioned lighting design documents."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    @staticmethod
    def _user_display_name(user: User | None) -> str | None:
        if user is None:
            return None
        return user.full_name or user.email

    @classmethod
    def _summary(cls, project: LightingProject) -> LightingProjectSummary:
        project_type: LightingProjectType = (
            "permanent" if project.document.get("projectType") == "permanent" else "landscape"
        )
        return LightingProjectSummary(
            id=project.id,
            workspace_id=project.workspace_id,
            contact_id=project.contact_id,
            contact_name=project.contact.full_name,
            service_location_id=project.service_location_id,
            opportunity_id=project.opportunity_id,
            assigned_user_id=project.assigned_user_id,
            name=project.name,
            project_type=project_type,
            status=cast(LightingProjectStatus, project.status),
            version=project.version,
            installation_shot_id=project.installation_shot_id,
            updated_by_id=project.updated_by_id,
            updater_name=cls._user_display_name(project.updated_by),
            created_at=project.created_at,
            updated_at=project.updated_at,
        )

    @staticmethod
    def _validate_selected_shot(
        document: LandscapeDraftDocument, installation_shot_id: str | None
    ) -> None:
        """Keep the metadata pointer inside the validated v2 document."""
        if installation_shot_id is None:
            return
        if installation_shot_id not in {shot.id for shot in document.shots}:
            raise ValidationError("Selected installation sheet is missing from the project")

    @classmethod
    def _detail(cls, project: LightingProject) -> LightingProjectDetail:
        summary = cls._summary(project)
        return LightingProjectDetail(
            **summary.model_dump(),
            document=LandscapeDraftDocument.model_validate(project.document),
            created_by_id=project.created_by_id,
        )

    async def _validate_references(
        self,
        workspace_id: uuid.UUID,
        payload: LightingProjectCreate,
    ) -> None:
        await assert_workspace_owned(
            self.db,
            Contact,
            payload.contact_id,
            workspace_id,
            detail="Contact not found",
        )

        if payload.service_location_id is not None:
            location = await assert_workspace_owned(
                self.db,
                ServiceLocation,
                payload.service_location_id,
                workspace_id,
                detail="Service location not found",
            )
            if location.contact_id != payload.contact_id:
                raise ValidationError("Service location does not belong to the selected contact")

        if payload.opportunity_id is not None:
            opportunity = await assert_workspace_owned(
                self.db,
                Opportunity,
                payload.opportunity_id,
                workspace_id,
                detail="Opportunity not found",
            )
            secondary_contact = await self.db.scalar(
                select(opportunity_contact_table.c.contact_id).where(
                    opportunity_contact_table.c.opportunity_id == opportunity.id,
                    opportunity_contact_table.c.contact_id == payload.contact_id,
                )
            )
            if opportunity.primary_contact_id != payload.contact_id and secondary_contact is None:
                raise ValidationError("Opportunity does not belong to the selected contact")

        if payload.assigned_user_id is not None:
            await assert_active_workspace_member(self.db, workspace_id, payload.assigned_user_id)

    async def list_projects(
        self,
        workspace_id: uuid.UUID,
        *,
        search: str | None = None,
        status: LightingProjectStatus | None = None,
        project_type: LightingProjectType | None = None,
        contact_id: int | None = None,
        opportunity_id: uuid.UUID | None = None,
        assigned_user_id: int | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> PaginatedLightingProjects:
        """List projects newest-first using only workspace-scoped rows."""

        query = (
            select(LightingProject)
            .where(LightingProject.workspace_id == workspace_id)
            .options(
                selectinload(LightingProject.contact),
                selectinload(LightingProject.updated_by),
            )
        )
        if status is not None:
            query = query.where(LightingProject.status == status)
        if project_type is not None:
            # simplification: JSONB filtering scans a workspace's projects; promote this
            # discriminator to an indexed column if workspaces reach thousands of designs.
            query = query.where(
                func.coalesce(LightingProject.document["projectType"].astext, "landscape")
                == project_type
            )
        if contact_id is not None:
            query = query.where(LightingProject.contact_id == contact_id)
        if opportunity_id is not None:
            query = query.where(LightingProject.opportunity_id == opportunity_id)
        if assigned_user_id is not None:
            query = query.where(LightingProject.assigned_user_id == assigned_user_id)

        normalized_search = (search or "").strip()
        if normalized_search:
            pattern = f"%{normalized_search}%"
            query = query.join(Contact, Contact.id == LightingProject.contact_id).where(
                or_(
                    LightingProject.name.ilike(pattern),
                    Contact.first_name.ilike(pattern),
                    Contact.last_name.ilike(pattern),
                    Contact.company_name.ilike(pattern),
                )
            )

        query = query.order_by(LightingProject.updated_at.desc(), LightingProject.id.desc())
        result = await paginate(self.db, query, page=page, page_size=page_size)
        return PaginatedLightingProjects(
            **result.to_dict([self._summary(project) for project in result.items])
        )

    async def create_project(
        self,
        workspace_id: uuid.UUID,
        payload: LightingProjectCreate,
        *,
        user_id: int | None,
    ) -> LightingProjectDetail:
        """Create a customer-linked project at concurrency version one."""

        await self._validate_references(workspace_id, payload)
        now = datetime.now(UTC)
        document = (
            payload.document or empty_landscape_document(now, payload.project_type)
        ).with_server_timestamp(now)
        self._validate_selected_shot(document, payload.installation_shot_id)
        project = LightingProject(
            workspace_id=workspace_id,
            contact_id=payload.contact_id,
            service_location_id=payload.service_location_id,
            opportunity_id=payload.opportunity_id,
            assigned_user_id=payload.assigned_user_id,
            name=payload.name,
            status="active",
            document=document.model_dump(mode="json", by_alias=True),
            version=1,
            installation_shot_id=payload.installation_shot_id,
            created_by_id=user_id,
            updated_by_id=user_id,
            created_at=now,
            updated_at=now,
        )
        self.db.add(project)
        await self.db.commit()
        await self.db.refresh(project, ["contact", "updated_by"])
        return self._detail(project)

    async def get_project(
        self, workspace_id: uuid.UUID, project_id: uuid.UUID
    ) -> LightingProjectDetail:
        """Fetch one same-workspace project and its complete current document."""

        result = await self.db.execute(
            select(LightingProject)
            .where(
                LightingProject.id == project_id,
                LightingProject.workspace_id == workspace_id,
            )
            .options(
                selectinload(LightingProject.contact),
                selectinload(LightingProject.updated_by),
            )
        )
        project = result.scalar_one_or_none()
        if project is None:
            raise NotFoundError("Lighting project not found")
        return self._detail(project)

    async def update_project(
        self,
        workspace_id: uuid.UUID,
        project_id: uuid.UUID,
        payload: LightingProjectUpdate,
        *,
        user_id: int | None,
    ) -> LightingProjectDetail:
        """Lock, compare, and replace project state without silent overwrites."""

        result = await self.db.execute(
            select(LightingProject)
            .where(
                LightingProject.id == project_id,
                LightingProject.workspace_id == workspace_id,
            )
            .options(
                selectinload(LightingProject.contact),
                selectinload(LightingProject.updated_by),
            )
            .with_for_update()
        )
        project = result.scalar_one_or_none()
        if project is None:
            raise NotFoundError("Lighting project not found")

        if project.version != payload.expected_version:
            raise ConflictError(
                "Lighting project changed since this draft was loaded",
                code="lighting_project_version_conflict",
                details={
                    "current_version": project.version,
                    "updater_name": self._user_display_name(project.updated_by),
                    "updated_at": project.updated_at.isoformat(),
                },
            )

        now = datetime.now(UTC)
        current_document = LandscapeDraftDocument.model_validate(project.document)
        next_document = (
            payload.document.with_server_timestamp(now)
            if "document" in payload.model_fields_set and payload.document is not None
            else current_document
        )
        if next_document.project_type != current_document.project_type:
            raise ValidationError("Project type cannot be changed")
        next_installation_shot_id = (
            payload.installation_shot_id
            if "installation_shot_id" in payload.model_fields_set
            else project.installation_shot_id
        )
        self._validate_selected_shot(next_document, next_installation_shot_id)

        if "name" in payload.model_fields_set and payload.name is not None:
            project.name = payload.name
        if "status" in payload.model_fields_set and payload.status is not None:
            project.status = payload.status
        if "document" in payload.model_fields_set and payload.document is not None:
            project.document = next_document.model_dump(mode="json", by_alias=True)
        if "installation_shot_id" in payload.model_fields_set:
            project.installation_shot_id = payload.installation_shot_id

        project.version += 1
        project.updated_by_id = user_id
        project.updated_at = now
        await self.db.commit()
        await self.db.refresh(project, ["contact", "updated_by"])
        return self._detail(project)
