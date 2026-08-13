"""Job-completion wiring for durable equipment ownership tags."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.jobs.job_service import JobService

pytestmark = pytest.mark.asyncio


async def test_completed_job_persists_all_classified_owner_tags() -> None:
    workspace_id = uuid.uuid4()
    completed_job = SimpleNamespace(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        contact_id=42,
        lighting_project_id=uuid.uuid4(),
        lighting_project=SimpleNamespace(
            document={
                "shots": [
                    {
                        "design": {
                            "items": [
                                {
                                    "productId": "fixture-transformer",
                                    "catalogSku": "best-luxor",
                                }
                            ]
                        }
                    }
                ]
            }
        ),
        source_quote=None,
    )
    db = MagicMock()
    db.scalar = AsyncMock(return_value=completed_job)
    add_tags = AsyncMock()
    tag_service = SimpleNamespace(add_tags_to_contact=add_tags)

    with patch("app.services.jobs.job_service.TagService", return_value=tag_service):
        names = await JobService(db)._tag_completed_system(completed_job)

    assert names == ("Lighting System", "Luxor System")
    add_tags.assert_awaited_once_with(
        workspace_id=workspace_id,
        contact_id=42,
        names=["Lighting System", "Luxor System"],
        color="#ffb90a",
    )


async def test_completed_service_job_does_not_create_owner_tags() -> None:
    completed_job = SimpleNamespace(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        contact_id=42,
        lighting_project_id=None,
        lighting_project=None,
        source_quote=None,
        title="Install Luxor repair",
    )
    db = MagicMock()
    db.scalar = AsyncMock(return_value=completed_job)
    add_tags = AsyncMock()
    tag_service = SimpleNamespace(add_tags_to_contact=add_tags)

    with patch("app.services.jobs.job_service.TagService", return_value=tag_service):
        names = await JobService(db)._tag_completed_system(completed_job)

    assert names == ()
    add_tags.assert_not_awaited()
