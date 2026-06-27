"""Logic tests for JobberTechnicianSync against a fake async session.

Follows the repo convention of mocking the DB session rather than standing up
Postgres: ``sync()`` issues a single ``execute`` (loading existing
Jobber-sourced technicians) and otherwise works in memory via ``add`` and field
mutation, so the create/update/deactivate decisions are fully assertable here.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.field_service import Technician
from app.services.jobber.mapping import EXTERNAL_SOURCE
from app.services.jobber.sync import JobberTechnicianSync

WS_ID = uuid.uuid4()


def _existing(ext_id: str, **overrides) -> Technician:
    fields = {
        "workspace_id": WS_ID,
        "external_source": EXTERNAL_SOURCE,
        "external_id": ext_id,
        "name": "Existing Tech",
        "email": "old@example.com",
        "phone": None,
        "is_active": True,
    }
    fields.update(overrides)
    return Technician(**fields)


def _fake_db(existing: list[Technician]) -> MagicMock:
    db = MagicMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = existing
    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


def _node(ext_id: str, **overrides) -> dict:
    node = {
        "id": ext_id,
        "name": {"full": "Feed Tech"},
        "email": {"raw": "new@example.com"},
        "phone": {"friendly": "(555) 000-1111"},
    }
    node.update(overrides)
    return node


@pytest.mark.asyncio
async def test_creates_new_technicians() -> None:
    db = _fake_db([])
    crew_id = uuid.uuid4()
    sync = JobberTechnicianSync(db, WS_ID)

    result = await sync.sync([_node("A"), _node("B")], default_crew_id=crew_id)

    assert result.created == 2
    assert result.updated == 0
    assert db.add.call_count == 2
    added = [call.args[0] for call in db.add.call_args_list]
    assert all(t.crew_id == crew_id for t in added)
    assert all(t.is_active for t in added)
    assert {t.external_id for t in added} == {"A", "B"}


@pytest.mark.asyncio
async def test_updates_only_changed_fields() -> None:
    tech = _existing("A", email="old@example.com")
    db = _fake_db([tech])
    sync = JobberTechnicianSync(db, WS_ID)

    result = await sync.sync([_node("A", email={"raw": "new@example.com"})])

    assert result.updated == 1
    assert result.created == 0
    assert tech.email == "new@example.com"
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_unchanged_when_identical() -> None:
    tech = _existing("A", name="Feed Tech", email="new@example.com", phone="(555) 000-1111")
    db = _fake_db([tech])
    sync = JobberTechnicianSync(db, WS_ID)

    result = await sync.sync([_node("A")])

    assert result.unchanged == 1
    assert result.updated == 0


@pytest.mark.asyncio
async def test_reactivates_inactive_technician() -> None:
    tech = _existing(
        "A",
        name="Feed Tech",
        email="new@example.com",
        phone="(555) 000-1111",
        is_active=False,
    )
    db = _fake_db([tech])
    sync = JobberTechnicianSync(db, WS_ID)

    result = await sync.sync([_node("A")])

    assert result.updated == 1
    assert tech.is_active is True


@pytest.mark.asyncio
async def test_skips_unmappable_node() -> None:
    db = _fake_db([])
    sync = JobberTechnicianSync(db, WS_ID)

    result = await sync.sync([_node(None), _node("B")])

    assert result.skipped == 1
    assert result.created == 1
    assert len(result.errors) == 1


@pytest.mark.asyncio
async def test_deactivate_missing_marks_absent_inactive() -> None:
    gone = _existing("GONE", is_active=True)
    db = _fake_db([gone])
    sync = JobberTechnicianSync(db, WS_ID)

    result = await sync.sync([_node("B")], deactivate_missing=True)

    assert result.created == 1
    assert result.deactivated == 1
    assert gone.is_active is False


@pytest.mark.asyncio
async def test_deactivate_missing_off_by_default() -> None:
    gone = _existing("GONE", is_active=True)
    db = _fake_db([gone])
    sync = JobberTechnicianSync(db, WS_ID)

    result = await sync.sync([_node("B")])

    assert result.deactivated == 0
    assert gone.is_active is True


@pytest.mark.asyncio
async def test_duplicate_id_in_feed_creates_once() -> None:
    db = _fake_db([])
    sync = JobberTechnicianSync(db, WS_ID)

    result = await sync.sync([_node("A"), _node("A")])

    assert result.created == 1
    assert result.unchanged == 1
    assert db.add.call_count == 1
