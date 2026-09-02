"""Contracts and real-DB coverage for landscape lighting project persistence."""

import base64
import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, get_membership
from app.api.v1 import lighting_projects as lighting_projects_api
from app.core.encryption import hash_phone, hash_value
from app.db.session import AsyncSessionLocal, engine
from app.models.contact import Contact
from app.models.field_service import ServiceLocation
from app.models.lighting_project import LightingProject
from app.models.opportunity import Opportunity
from app.models.pipeline import Pipeline
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership
from app.schemas import lighting_project as lighting_schema
from app.schemas.lighting_project import (
    LandscapeDraftDocument,
    LightingProjectCreate,
    LightingProjectUpdate,
)
from app.services.exceptions import ConflictError, NotFoundError, ValidationError
from app.services.lighting_projects.project_service import LightingProjectService
from app.services.messaging.media_storage import StoredMedia

WS_ID = uuid.uuid4()
PROJECT_ID = uuid.uuid4()
NOW = datetime.now(UTC)


WORKSPACE_KEY_PREFIX = "workspaces/11111111-1111-1111-1111-111111111111/lighting-projects"
_STORED_KEY = f"{WORKSPACE_KEY_PREFIX}/22222222-2222-2222-2222-222222222222/abc123.png"
_STORED_REF = f"{lighting_schema.LIGHTING_IMAGE_REF_PREFIX}{_STORED_KEY}"


def _photo() -> dict[str, object]:
    return {"dataUrl": "data:image/png;base64,AAAA", "width": 1200, "height": 800}


def _document(
    *,
    updated_at: datetime | None = None,
    shot_id: str = "shot-1",
    project_type: str = "landscape",
) -> dict[str, object]:
    return {
        "version": 2,
        "projectType": project_type,
        "activeShotId": shot_id,
        "shots": [
            {
                "id": shot_id,
                "photo": _photo(),
                "design": {
                    "calibration": None,
                    "runs": [
                        {
                            "id": "run-1",
                            "productId": "c9-roofline",
                            "points": [{"x": 10, "y": 20}, {"x": 50, "y": 20}],
                            "scaleSlot": 2,
                            "permanentComplexity": "complex",
                            "elevation": "side",
                            "roofPitch": "steep",
                            "spacingIn": 12,
                            "colors": ["#f8d46b"],
                            "bulbScale": 1,
                            "circuitLabel": "C1",
                            "transformerId": "transformer-1",
                            "wireGauge": 12,
                            "sourceVoltage": 13,
                        }
                    ],
                    "items": [
                        {
                            "id": "fixture-1",
                            "productId": "spotlight",
                            "at": {"x": 30, "y": 40},
                            "sizePx": 32,
                            "iconScale": 1.4,
                            "beamAngleDeg": 40,
                            "beamRotationDeg": 0,
                            "circuitId": "run-1",
                            "bistroRunId": "run-1",
                            "markerColor": "#F2C94C",
                            "catalogItemOverride": True,
                        },
                        {
                            "id": "transformer-1",
                            "productId": "fixture-transformer",
                            "at": {"x": 20, "y": 60},
                            "sizePx": 32,
                        },
                    ],
                    "planImages": [
                        {
                            "id": "plan-image-1",
                            "dataUrl": "data:image/png;base64,AAAA",
                            "name": "Pool equipment detail.png",
                            "at": {"x": 300, "y": 240},
                            "widthPx": 240,
                            "heightPx": 160,
                        }
                    ],
                },
                "dusk": 0.35,
            }
        ],
        "updatedAt": (updated_at or NOW).isoformat(),
        "proposal": {
            "selectedTierKey": "better",
            "selectedCarePlanKey": "essential",
        },
        "bomLineItems": [
            {
                "id": "manual-bom-1",
                "description": "Copper ground stake",
                "sku": "STAKE-CU",
                "quantity": 4,
                "unit": "each",
            }
        ],
        "procurement": {
            "fixture:catalog-1": {
                "catalogItemId": "catalog-1",
                "catalogSku": "UP-100",
                "description": "Brass uplight",
                "manufacturer": "Tribunal Lighting",
                "supplier": "Local Supply",
                "neededQuantity": 8,
                "orderedQuantity": 6,
                "receivedQuantity": 2,
                "unitCost": 84.5,
                "supplierNote": "PO-1042",
            }
        },
    }


class TestLandscapeDraftSchema:
    def test_accepts_empty_and_populated_documents(self) -> None:
        empty = LandscapeDraftDocument.model_validate(
            {
                "version": 2,
                "activeShotId": None,
                "shots": [],
                "updatedAt": NOW.isoformat(),
            }
        )
        populated = LandscapeDraftDocument.model_validate(_document())

        assert empty.shots == []
        assert empty.bom_line_items == []
        assert populated.active_shot_id == "shot-1"
        assert populated.shots[0].design.plan_images[0].name == "Pool equipment detail.png"
        assert populated.shots[0].design.runs[0].wire_gauge == 12
        # Rep-set drawing state the designer stores on every save. Rejecting any of
        # these 422s the autosave, which then blocks the proposal outright.
        assert populated.shots[0].design.runs[0].scale_slot == 2
        assert populated.shots[0].design.runs[0].permanent_complexity == "complex"
        assert populated.shots[0].design.runs[0].roof_pitch == "steep"
        assert populated.shots[0].design.items[0].catalog_item_override is True
        assert populated.shots[0].design.items[0].circuit_id == "run-1"
        assert populated.shots[0].design.items[0].bistro_run_id == "run-1"
        assert populated.shots[0].design.items[0].marker_color == "#F2C94C"
        assert populated.shots[0].design.items[0].icon_scale == 1.4
        assert populated.proposal.selected_tier_key == "better"
        assert populated.proposal.selected_care_plan_key == "essential"
        assert populated.bom_line_items[0].description == "Copper ground stake"
        assert populated.bom_line_items[0].quantity == 4
        procurement = populated.procurement["fixture:catalog-1"]
        assert procurement.description == "Brass uplight"
        assert procurement.needed_quantity == 8
        assert procurement.unit_cost == 84.5
        assert populated.settings.paper_size == "tabloid"
        assert populated.active_workflow_tab is None
        serialized = populated.model_dump(mode="json", by_alias=True)
        assert serialized["activeShotId"] == "shot-1"
        assert serialized["bomLineItems"][0]["sku"] == "STAKE-CU"
        run = serialized["shots"][0]["design"]["runs"][0]
        assert run["permanentComplexity"] == "complex"
        assert run["scaleSlot"] == 2
        assert run["elevation"] == "side"
        assert run["roofPitch"] == "steep"

    def test_normalizes_retired_aerial_complexity_without_losing_the_run(self) -> None:
        document = _document()
        document["shots"][0]["design"]["runs"][0]["permanentComplexity"] = "aerial"
        populated = LandscapeDraftDocument.model_validate(document)

        run = populated.shots[0].design.runs[0]
        assert run.permanent_complexity == "standard"
        assert run.model_dump(mode="json", by_alias=True)["permanentComplexity"] == "standard"

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda document: document.update(activeShotId="missing"),
            lambda document: document["shots"].append(document["shots"][0]),
            lambda document: document["shots"][0]["photo"].update(width=0),
            lambda document: document["shots"][0]["design"]["runs"].append(
                document["shots"][0]["design"]["runs"][0]
            ),
            lambda document: document["shots"][0]["design"]["planImages"].append(
                document["shots"][0]["design"]["planImages"][0]
            ),
            lambda document: document["shots"][0]["design"]["planImages"][0].update(
                dataUrl="https://example.com/not-embedded.png"
            ),
            lambda document: document["shots"][0]["design"]["items"][0].update(
                circuitId="missing-run"
            ),
            lambda document: document["shots"][0]["design"]["runs"][0].update(
                transformerId="missing-transformer"
            ),
            lambda document: document["bomLineItems"].append(document["bomLineItems"][0]),
            lambda document: document["bomLineItems"][0].update(quantity=-1),
            lambda document: document["shots"][0]["design"]["items"][0].update(iconScale=3),
            lambda document: document["procurement"]["fixture:catalog-1"].update(neededQuantity=-1),
            lambda document: document["shots"][0]["design"]["runs"][0].update(elevation="left"),
            lambda document: document["shots"][0]["design"]["runs"][0].update(roofPitch="vertical"),
            lambda document: document["shots"][0]["design"]["runs"][0].update(
                permanentComplexity="unknown"
            ),
            lambda document: document.update(version=1),
            lambda document: document.update(version=3),
        ],
    )
    def test_rejects_invalid_references_dimensions_ids_and_versions(self, mutate: object) -> None:
        document = _document()
        mutate(document)  # type: ignore[operator]
        with pytest.raises(PydanticValidationError):
            LandscapeDraftDocument.model_validate(document)

    def test_accepts_a_document_mixing_data_urls_and_stored_image_references(self) -> None:
        """A half-migrated document must still validate; see the plan's Compatibility."""
        document = _document()
        shot = document["shots"][0]  # type: ignore[index]
        shot["photo"]["dataUrl"] = _STORED_REF
        shot["design"]["annotations"] = [
            {
                "id": "note-1",
                "type": "photo",
                "at": {"x": 5, "y": 5},
                "imageDataUrl": _STORED_REF,
            }
        ]
        # planImages deliberately left inline, so this document holds both shapes.
        parsed = LandscapeDraftDocument.model_validate(document)
        assert lighting_schema.lighting_image_key(parsed.shots[0].photo.data_url) == _STORED_KEY
        assert parsed.shots[0].design.plan_images[0].data_url.startswith("data:image/")

    @pytest.mark.parametrize(
        "value",
        [
            "lighting-image:",
            "lighting-image:/absolute/key.png",
            "lighting-image:workspaces/../../etc/passwd",
            "lighting-image:workspaces/a//b.png",
            "lighting-image:workspaces/a/b.png?x=1",
            "lighting-image:" + "a" * 260,
            "https://example.com/remote.png",
            "file:///etc/passwd",
            "",
        ],
    )
    def test_rejects_unsafe_or_foreign_image_values(self, value: str) -> None:
        document = _document()
        document["shots"][0]["photo"]["dataUrl"] = value  # type: ignore[index]
        with pytest.raises(PydanticValidationError):
            LandscapeDraftDocument.model_validate(document)

    def test_resolved_url_is_length_bounded_so_it_cannot_re_bloat_the_document(self) -> None:
        document = _document()
        document["shots"][0]["photo"]["resolvedUrl"] = "h" * 5000  # type: ignore[index]
        with pytest.raises(PydanticValidationError):
            LandscapeDraftDocument.model_validate(document)

    def test_caps_shots_and_complete_serialized_size(self, monkeypatch: pytest.MonkeyPatch) -> None:
        too_many = _document()
        too_many["shots"] = [
            {**too_many["shots"][0], "id": f"shot-{index}"}  # type: ignore[index]
            for index in range(7)
        ]
        with pytest.raises(PydanticValidationError):
            LandscapeDraftDocument.model_validate(too_many)

        monkeypatch.setattr(lighting_schema, "MAX_LANDSCAPE_DOCUMENT_BYTES", 250)
        with pytest.raises(PydanticValidationError, match="exceeds"):
            LandscapeDraftDocument.model_validate(_document())

    def test_rejects_null_or_noop_updates(self) -> None:
        with pytest.raises(PydanticValidationError):
            LightingProjectUpdate(expected_version=1)
        with pytest.raises(PydanticValidationError):
            LightingProjectUpdate(expected_version=1, document=None)

    def test_selected_installation_sheet_must_reference_a_saved_shot(self) -> None:
        document = LandscapeDraftDocument.model_validate(_document())
        created = LightingProjectCreate(
            contact_id=42,
            name="Patio",
            document=document,
            installation_shot_id="shot-1",
        )
        assert created.installation_shot_id == "shot-1"

        with pytest.raises(PydanticValidationError, match="saved shot"):
            LightingProjectCreate(
                contact_id=42,
                name="Patio",
                document=document,
                installation_shot_id="missing",
            )


@asynccontextmanager
async def _test_lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield


def _api_response(**overrides: object) -> dict[str, object]:
    response: dict[str, object] = {
        "id": str(PROJECT_ID),
        "workspace_id": str(WS_ID),
        "contact_id": 42,
        "contact_name": "Pat Lee",
        "service_location_id": None,
        "opportunity_id": None,
        "assigned_user_id": None,
        "name": "Patio lighting",
        "project_type": "landscape",
        "status": "active",
        "version": 1,
        "installation_shot_id": None,
        "updated_by_id": 7,
        "updater_name": "Manager",
        "created_at": NOW.isoformat(),
        "updated_at": NOW.isoformat(),
        "created_by_id": 7,
        "document": {
            "version": 2,
            "projectType": "landscape",
            "activeShotId": None,
            "shots": [],
            "updatedAt": NOW.isoformat(),
        },
    }
    response.update(overrides)
    return response


def _api_summary_response(**overrides: object) -> dict[str, object]:
    response = _api_response(**overrides)
    response.pop("created_by_id")
    response.pop("document")
    return response


async def _api_client(role: str, service: AsyncMock) -> AsyncIterator[AsyncClient]:
    app = FastAPI(lifespan=_test_lifespan)

    async def override_db() -> AsyncIterator[AsyncMock]:
        yield AsyncMock()

    user = MagicMock(id=7, is_active=True)
    membership = MagicMock(workspace_id=WS_ID, user_id=7, role=role)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_membership] = lambda: membership
    app.include_router(
        lighting_projects_api.router,
        prefix="/api/v1/workspaces/{workspace_id}/lighting-projects",
    )
    with patch.object(lighting_projects_api, "LightingProjectService", return_value=service):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            yield client


@pytest.fixture
async def manager_client() -> AsyncIterator[AsyncClient]:
    service = AsyncMock()
    service.list_projects.return_value = {
        "items": [_api_summary_response()],
        "total": 1,
        "page": 1,
        "page_size": 50,
        "pages": 1,
    }
    service.create_project.return_value = _api_response()
    service.get_project.return_value = _api_response()
    service.get_project_revision.return_value = {"version": 1}
    service.update_project.return_value = _api_response(version=2)
    async for client in _api_client("manager", service):
        yield client


@pytest.fixture
async def sales_client() -> AsyncIterator[AsyncClient]:
    async for client in _api_client("sales_rep", AsyncMock()):
        yield client


class TestLightingProjectApiPermissions:
    @pytest.mark.asyncio
    async def test_manager_can_read_and_write(self, manager_client: AsyncClient) -> None:
        base = f"/api/v1/workspaces/{WS_ID}/lighting-projects"
        list_response = await manager_client.get(base)
        assert list_response.status_code == 200
        assert "document" not in list_response.json()["items"][0]
        revision_response = await manager_client.get(f"{base}/{PROJECT_ID}/revision")
        assert revision_response.status_code == 200
        assert revision_response.json() == {"version": 1}
        response = await manager_client.post(
            base, json={"contact_id": 42, "name": "Patio lighting"}
        )
        assert response.status_code == 201
        assert response.json()["document"]["activeShotId"] is None

    @pytest.mark.asyncio
    async def test_role_without_billing_capabilities_is_denied(
        self, sales_client: AsyncClient
    ) -> None:
        base = f"/api/v1/workspaces/{WS_ID}/lighting-projects"
        assert (await sales_client.get(base)).status_code == 403
        assert (await sales_client.get(f"{base}/{PROJECT_ID}/revision")).status_code == 403
        assert (
            await sales_client.post(base, json={"contact_id": 42, "name": "Patio lighting"})
        ).status_code == 403


@pytest.fixture
async def fresh_engine_pool() -> AsyncIterator[None]:
    await engine.dispose()
    yield
    await engine.dispose()


async def _make_workspace(db: AsyncSession, label: str) -> Workspace:
    workspace = Workspace(id=uuid.uuid4(), name=label, slug=f"lighting-{uuid.uuid4().hex[:10]}")
    db.add(workspace)
    await db.flush()
    return workspace


async def _make_member(db: AsyncSession, workspace_id: uuid.UUID, *, name: str) -> User:
    email = f"{uuid.uuid4().hex[:10]}@example.com"
    user = User(
        email=email,
        email_hash=hash_value(email),
        hashed_password="x",
        full_name=name,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    db.add(WorkspaceMembership(workspace_id=workspace_id, user_id=user.id, role="manager"))
    await db.flush()
    return user


async def _make_contact(db: AsyncSession, workspace_id: uuid.UUID, *, name: str) -> Contact:
    phone = f"+1555{uuid.uuid4().int % 10_000_000:07d}"
    contact = Contact(
        workspace_id=workspace_id,
        first_name=name,
        phone_number=phone,
        phone_hash=hash_phone(phone),
    )
    db.add(contact)
    await db.flush()
    return contact


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_list_get_update_archive_and_stale_conflict(
    fresh_engine_pool: None,
) -> None:
    async with AsyncSessionLocal() as db:
        workspace = await _make_workspace(db, "Lighting Co")
        creator = await _make_member(db, workspace.id, name="Morgan Manager")
        contact = await _make_contact(db, workspace.id, name="Pat")
        service = LightingProjectService(db)
        workspace_id = workspace.id
        creator_id = creator.id
        browser_time = datetime(2000, 1, 1, tzinfo=UTC)

        created = await service.create_project(
            workspace_id,
            LightingProjectCreate(
                contact_id=contact.id,
                name="  Patio lighting  ",
                document=LandscapeDraftDocument.model_validate(_document(updated_at=browser_time)),
                installation_shot_id="shot-1",
            ),
            user_id=creator_id,
        )
        assert created.name == "Patio lighting"
        assert created.version == 1
        assert created.contact_name == "Pat"
        assert created.installation_shot_id == "shot-1"
        assert created.updater_name == "Morgan Manager"
        assert created.document.updated_at > browser_time
        assert (await service.get_project_revision(workspace_id, created.id)).version == 1

        fetched = await service.get_project(workspace_id, created.id)
        assert fetched.document.shots[0].id == "shot-1"

        accepted = await service.update_project(
            workspace_id,
            created.id,
            LightingProjectUpdate(
                expected_version=1,
                name="Patio and path lighting",
                document=LandscapeDraftDocument.model_validate(_document(shot_id="shot-new")),
                installation_shot_id="shot-new",
            ),
            user_id=creator_id,
        )
        assert accepted.version == 2
        assert (await service.get_project_revision(workspace_id, created.id)).version == 2
        assert accepted.document.active_shot_id == "shot-new"
        assert accepted.installation_shot_id == "shot-new"

        with pytest.raises(ValidationError, match="Selected installation sheet"):
            await service.update_project(
                workspace_id,
                created.id,
                LightingProjectUpdate(
                    expected_version=2,
                    document=LandscapeDraftDocument.model_validate(_document(shot_id="shot-other")),
                ),
                user_id=creator_id,
            )
        await db.rollback()

        with pytest.raises(ConflictError) as conflict:
            await service.update_project(
                workspace_id,
                created.id,
                LightingProjectUpdate(expected_version=1, status="archived"),
                user_id=creator_id,
            )
        assert conflict.value.details["current_version"] == 2
        await db.rollback()
        unchanged = await service.get_project(workspace_id, created.id)
        assert unchanged.status == "active"
        assert unchanged.document.active_shot_id == "shot-new"

        archived = await service.update_project(
            workspace_id,
            created.id,
            LightingProjectUpdate(expected_version=2, status="archived"),
            user_id=creator_id,
        )
        assert archived.version == 3
        assert archived.status == "archived"

        assert (await service.list_projects(workspace_id, status="active")).total == 0
        archived_page = await service.list_projects(
            workspace_id, status="archived", search="Pat", page=1, page_size=1
        )
        assert archived_page.total == 1
        assert archived_page.items[0].id == created.id
        assert archived_page.pages == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_permanent_project_persists_client_design_reopen_and_resave(
    fresh_engine_pool: None,
) -> None:
    async with AsyncSessionLocal() as db:
        workspace = await _make_workspace(db, "Permanent Lighting Co")
        creator = await _make_member(db, workspace.id, name="Morgan Manager")
        contact = await _make_contact(db, workspace.id, name="Avery")
        service = LightingProjectService(db)

        created = await service.create_project(
            workspace.id,
            LightingProjectCreate(
                contact_id=contact.id,
                name="Avery permanent roofline",
                project_type="permanent",
                document=LandscapeDraftDocument.model_validate(_document(project_type="permanent")),
            ),
            user_id=creator.id,
        )
        assert created.contact_id == contact.id
        assert created.contact_name == "Avery"
        assert created.project_type == "permanent"
        assert created.document.project_type == "permanent"

        permanent_projects = await service.list_projects(workspace.id, project_type="permanent")
        landscape_projects = await service.list_projects(workspace.id, project_type="landscape")
        assert [project.id for project in permanent_projects.items] == [created.id]
        assert landscape_projects.total == 0

        reopened = await service.get_project(workspace.id, created.id)
        assert reopened.document.shots[0].design.runs[0].product_id == "c9-roofline"

        first_resave = await service.update_project(
            workspace.id,
            created.id,
            LightingProjectUpdate(
                expected_version=1,
                document=LandscapeDraftDocument.model_validate(
                    _document(project_type="permanent", shot_id="permanent-edit-1")
                ),
            ),
            user_id=creator.id,
        )
        assert first_resave.version == 2

        reopened_again = await service.get_project(workspace.id, created.id)
        assert reopened_again.document.active_shot_id == "permanent-edit-1"
        second_resave = await service.update_project(
            workspace.id,
            created.id,
            LightingProjectUpdate(
                expected_version=2,
                document=LandscapeDraftDocument.model_validate(
                    _document(project_type="permanent", shot_id="permanent-edit-2")
                ),
            ),
            user_id=creator.id,
        )
        assert second_resave.version == 3
        assert second_resave.document.active_shot_id == "permanent-edit-2"

        with pytest.raises(ValidationError, match="Project type cannot be changed"):
            await service.update_project(
                workspace.id,
                created.id,
                LightingProjectUpdate(
                    expected_version=3,
                    document=LandscapeDraftDocument.model_validate(_document()),
                ),
                user_id=creator.id,
            )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_workspace_isolation_covers_project_and_every_linked_crm_id(
    fresh_engine_pool: None,
) -> None:
    async with AsyncSessionLocal() as db:
        local_workspace = await _make_workspace(db, "Local Lighting")
        foreign_workspace = await _make_workspace(db, "Foreign Lighting")
        local_user = await _make_member(db, local_workspace.id, name="Local Manager")
        foreign_user = await _make_member(db, foreign_workspace.id, name="Foreign Manager")
        local_contact = await _make_contact(db, local_workspace.id, name="Local")
        second_local_contact = await _make_contact(db, local_workspace.id, name="Second")
        foreign_contact = await _make_contact(db, foreign_workspace.id, name="Foreign")

        local_location = ServiceLocation(
            workspace_id=local_workspace.id,
            contact_id=second_local_contact.id,
            name="Wrong customer site",
        )
        foreign_location = ServiceLocation(
            workspace_id=foreign_workspace.id,
            contact_id=foreign_contact.id,
            name="Foreign site",
        )
        pipeline = Pipeline(workspace_id=foreign_workspace.id, name="Foreign sales")
        db.add_all([local_location, foreign_location, pipeline])
        await db.flush()
        foreign_opportunity = Opportunity(
            workspace_id=foreign_workspace.id,
            pipeline_id=pipeline.id,
            name="Foreign deal",
        )
        db.add(foreign_opportunity)
        await db.flush()

        service = LightingProjectService(db)
        with pytest.raises(HTTPException) as foreign_contact_error:
            await service.create_project(
                local_workspace.id,
                LightingProjectCreate(contact_id=foreign_contact.id, name="Invalid customer"),
                user_id=local_user.id,
            )
        assert foreign_contact_error.value.status_code == 404

        with pytest.raises(HTTPException):
            await service.create_project(
                local_workspace.id,
                LightingProjectCreate(
                    contact_id=local_contact.id,
                    service_location_id=foreign_location.id,
                    name="Invalid site",
                ),
                user_id=local_user.id,
            )
        with pytest.raises(ValidationError):
            await service.create_project(
                local_workspace.id,
                LightingProjectCreate(
                    contact_id=local_contact.id,
                    service_location_id=local_location.id,
                    name="Mismatched site",
                ),
                user_id=local_user.id,
            )
        with pytest.raises(HTTPException):
            await service.create_project(
                local_workspace.id,
                LightingProjectCreate(
                    contact_id=local_contact.id,
                    opportunity_id=foreign_opportunity.id,
                    name="Invalid deal",
                ),
                user_id=local_user.id,
            )
        with pytest.raises(NotFoundError):
            await service.create_project(
                local_workspace.id,
                LightingProjectCreate(
                    contact_id=local_contact.id,
                    assigned_user_id=foreign_user.id,
                    name="Invalid assignee",
                ),
                user_id=local_user.id,
            )

        created = await service.create_project(
            local_workspace.id,
            LightingProjectCreate(contact_id=local_contact.id, name="Local project"),
            user_id=local_user.id,
        )
        with pytest.raises(NotFoundError):
            await service.get_project(foreign_workspace.id, created.id)
        with pytest.raises(NotFoundError):
            await service.get_project_revision(foreign_workspace.id, created.id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_saved_images_leave_the_database_and_come_back_as_signed_urls(
    fresh_engine_pool: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A data-URL save must persist a key, and a read must hand back a usable URL.

    This is the whole point of the change: base64 image bytes in this JSONB
    column are what filled the database volume.
    """
    storage = MagicMock()
    storage.upload_bytes.return_value = StoredMedia(object_key="k", size_bytes=1, sha256="d")
    storage.create_download_url.return_value = "https://bucket.example/signed"
    monkeypatch.setattr("app.services.lighting_projects.images._storage_or_none", lambda: storage)

    async with AsyncSessionLocal() as db:
        workspace = await _make_workspace(db, "Lighting Co")
        user = await _make_member(db, workspace.id, name="Morgan Manager")
        contact = await _make_contact(db, workspace.id, name="Pat")
        service = LightingProjectService(db)
        png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"pixels").decode()
        document = _document()
        document["shots"][0]["photo"]["dataUrl"] = f"data:image/png;base64,{png}"  # type: ignore[index]
        document["shots"][0]["design"]["planImages"][0]["dataUrl"] = (  # type: ignore[index]
            f"data:image/png;base64,{png}"
        )

        created = await service.create_project(
            workspace.id,
            LightingProjectCreate(
                contact_id=contact.id,
                name="Backyard",
                document=LandscapeDraftDocument.model_validate(document),
                installation_shot_id="shot-1",
            ),
            user_id=user.id,
        )

        stored_row = await db.get(LightingProject, created.id)
        assert stored_row is not None
        raw = json.dumps(stored_row.document)
        assert "data:image" not in raw, "image bytes must not reach the database"
        assert f"workspaces/{workspace.id}/lighting-projects/{created.id}/" in raw
        # No expiring URL may be persisted either.
        assert "https://bucket.example/signed" not in raw

        fetched = await service.get_project(workspace.id, created.id)
        assert fetched.document.shots[0].photo.resolved_url == "https://bucket.example/signed"
        assert fetched.document.shots[0].design.plan_images[0].resolved_url == (
            "https://bucket.example/signed"
        )

        # Round trip: saving the resolved document back keeps the key and drops the URL.
        resaved = await service.update_project(
            workspace.id,
            created.id,
            LightingProjectUpdate(expected_version=1, document=fetched.document),
            user_id=user.id,
        )
        resaved_row = await db.get(LightingProject, created.id)
        await db.refresh(resaved_row)
        assert resaved_row is not None
        resaved_raw = json.dumps(resaved_row.document)
        assert "https://bucket.example/signed" not in resaved_raw
        assert "data:image" not in resaved_raw
        assert resaved.version == 2

        # A save built on a superseded draft must be refused *before* it spends
        # bucket I/O; otherwise every losing autosave uploads orphaned objects.
        uploads_before_stale_save = storage.upload_bytes.call_count
        stale_document = LandscapeDraftDocument.model_validate(_document())
        with pytest.raises(ConflictError):
            await service.update_project(
                workspace.id,
                created.id,
                LightingProjectUpdate(expected_version=1, document=stale_document),
                user_id=user.id,
            )
        assert storage.upload_bytes.call_count == uploads_before_stale_save, (
            "a stale save must not upload anything"
        )
