"""Real-database proof that the lighting-image migration removes bytes safely.

The script rewrites production rows on a volume that is 68% full, so its two
guarantees are worth testing directly: a dry run writes nothing, and an applied
run leaves a document that no longer contains a single ``data:image`` payload.
"""

from __future__ import annotations

import argparse
import base64
import importlib.util
import json
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import pytest

from app.db.session import AsyncSessionLocal, engine
from app.models.contact import Contact
from app.models.lighting_project import LightingProject
from app.models.workspace import Workspace
from app.core.encryption import hash_phone
from app.services.messaging.media_storage import StoredMedia

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
async def fresh_engine_pool() -> AsyncIterator[None]:
    """The script disposes the shared engine, so isolate each test's pool."""
    await engine.dispose()
    yield
    await engine.dispose()


ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "scripts" / "ops" / "migrate_lighting_images.py"
PNG_DATA_URL = (
    "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"pixels" * 64).decode()
)


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migrate_lighting_images", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _document() -> dict:
    return {
        "version": 2,
        "projectType": "landscape",
        "activeShotId": "shot-1",
        "shots": [
            {
                "id": "shot-1",
                "photo": {"dataUrl": PNG_DATA_URL, "width": 100, "height": 80},
                "design": {
                    "calibration": None,
                    "runs": [],
                    "items": [],
                    "planImages": [
                        {
                            "id": "plan-1",
                            "dataUrl": PNG_DATA_URL,
                            "name": "detail.png",
                            "at": {"x": 1, "y": 2},
                            "widthPx": 10,
                            "heightPx": 10,
                        }
                    ],
                },
                "dusk": 0.3,
            }
        ],
        "updatedAt": "2026-01-01T00:00:00+00:00",
    }


async def _seed() -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        workspace = Workspace(id=uuid.uuid4(), name="Lighting", slug=f"lp-{uuid.uuid4().hex[:10]}")
        db.add(workspace)
        await db.flush()
        phone = f"+1555{uuid.uuid4().int % 10_000_000:07d}"
        contact = Contact(
            workspace_id=workspace.id,
            first_name="Pat",
            phone_number=phone,
            phone_hash=hash_phone(phone),
        )
        db.add(contact)
        await db.flush()
        project = LightingProject(
            workspace_id=workspace.id,
            contact_id=contact.id,
            name="Backyard",
            document=_document(),
        )
        db.add(project)
        await db.flush()
        await db.commit()
        return project.id


def _storage() -> MagicMock:
    storage = MagicMock()
    storage.upload_bytes.return_value = StoredMedia(object_key="k", size_bytes=1, sha256="d")
    return storage


async def _document_of(project_id: uuid.UUID) -> dict:
    async with AsyncSessionLocal() as db:
        project = await db.get(LightingProject, project_id)
        assert project is not None
        return dict(project.document)


async def test_dry_run_reports_bytes_and_writes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    script = load_script()
    monkeypatch.setattr(script.settings, "mms_storage_bucket", "test-bucket")
    project_id = await _seed()

    exit_code = await script._run(argparse.Namespace(apply=False, limit=5, project_id=project_id))

    assert exit_code == 0
    assert "data:image" in json.dumps(await _document_of(project_id))


async def test_apply_replaces_every_data_url_with_a_stored_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = load_script()
    monkeypatch.setattr(script.settings, "mms_storage_bucket", "test-bucket")
    monkeypatch.setattr(
        "app.services.lighting_projects.images._storage_or_none", lambda: _storage()
    )
    project_id = await _seed()
    before = json.dumps(await _document_of(project_id))

    exit_code = await script._run(argparse.Namespace(apply=True, limit=5, project_id=project_id))

    assert exit_code == 0
    after = json.dumps(await _document_of(project_id))
    assert "data:image" not in after
    assert "lighting-image:" in after
    assert "resolvedUrl" not in after, "expiring URLs must never reach the database"
    # The point of the migration: the base64 payload is gone from the column.
    assert script._inline_image_bytes(json.loads(before)) > 1000
    assert script._inline_image_bytes(json.loads(after)) == 0


async def test_apply_aborts_when_object_storage_is_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = load_script()
    monkeypatch.setattr(script.settings, "mms_storage_bucket", "")

    with pytest.raises(script.MigrationAbort, match="not configured"):
        await script._run(argparse.Namespace(apply=True, limit=5, project_id=None))
