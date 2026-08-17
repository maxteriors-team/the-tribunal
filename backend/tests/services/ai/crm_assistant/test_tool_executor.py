"""Tests for the CRM tool executor — workspace scoping + dispatch."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.services.ai.crm_assistant._contact_tools as contact_tools_module
from app.services.ai.crm_assistant._tool_executor import CRMToolExecutor
from app.services.ai.crm_assistant._tool_metadata import CRMToolMetadata, ToolRiskLevel
from app.services.ai.crm_assistant._tools import CRM_TOOLS, get_crm_tools


def test_tool_spec_handler_parity() -> None:
    """Every declared CRM tool has exactly one executor handler."""
    spec_names = {tool["function"]["name"] for tool in get_crm_tools()}
    assert spec_names, "CRM tool registry is empty"
    assert len(CRM_TOOLS) == len(spec_names)

    executor = CRMToolExecutor(db=MagicMock(), workspace_id=uuid.uuid4(), user_id=1)

    assert spec_names == set(executor.handlers)


def test_get_contact_context_is_explicitly_read_only() -> None:
    executor = CRMToolExecutor(db=MagicMock(), workspace_id=uuid.uuid4(), user_id=1)

    metadata = executor.tool_metadata["get_contact_context"]
    assert metadata.risk_level is ToolRiskLevel.LOW
    assert metadata.requires_approval is False
    assert metadata.requires_confirmation is False


@pytest.mark.asyncio
async def test_execute_unknown_tool_returns_error() -> None:
    """Unknown tool names should return a structured error, not raise."""
    executor = CRMToolExecutor(db=AsyncMock(), workspace_id=uuid.uuid4(), user_id=1)
    result = await executor.execute("nonexistent_tool", {})
    assert result["success"] is False
    assert result["code"] == "unknown_tool"
    assert "nonexistent_tool" in result["message"]
    assert result["retryable"] is False


@pytest.mark.asyncio
async def test_execute_handler_exception_returns_error() -> None:
    """Handler exceptions are caught and surfaced as success=False."""
    workspace_id = uuid.uuid4()

    # Mock db.execute to raise inside the handler
    db = AsyncMock()
    db.execute.side_effect = RuntimeError("db down")

    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=1)
    result = await executor.execute("search_contacts", {"query": "x"})
    assert result["success"] is False
    assert result["code"] == "internal"
    assert "search_contacts" in result["message"]
    # An unexpected bug must not tell the model to retry.
    assert result["retryable"] is False


@pytest.mark.asyncio
async def test_search_contacts_filters_by_workspace() -> None:
    """The contacts search must scope to the given workspace_id."""
    workspace_id = uuid.uuid4()

    captured_stmts: list[Any] = []
    captured_counts: list[Any] = []

    async def fake_execute(stmt: Any) -> Any:
        captured_stmts.append(stmt)
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        return result

    async def fake_scalar(stmt: Any) -> int:
        captured_counts.append(stmt)
        return 0

    db = AsyncMock()
    db.execute = fake_execute  # type: ignore[assignment]
    db.scalar = fake_scalar  # type: ignore[assignment]

    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=1)
    out = await executor.execute("search_contacts", {"query": "alice"})

    assert out["success"] is True
    assert out["returned"] == 0
    assert out["total"] == 0
    assert out["has_more"] is False
    # The bound parameters must include the workspace_id (multi-tenant scoping)
    # on both the fetch and the COUNT(*) that produces `total`.
    assert len(captured_stmts) == 1
    assert len(captured_counts) == 1
    for stmt in (*captured_stmts, *captured_counts):
        assert workspace_id in stmt.compile().params.values()


@pytest.mark.asyncio
async def test_search_contacts_returns_dated_followup_evidence() -> None:
    """Search results expose enough dated CRM evidence for grounded recommendations."""
    now = datetime(2026, 7, 10, 15, 30, tzinfo=UTC)
    contact = SimpleNamespace(
        id=7,
        first_name="Ava",
        last_name="Rivera",
        phone_number="+15555550123",
        email="ava@example.com",
        status="qualified",
        company_name="Rivera Co",
        lead_score=88,
        engagement_score=73,
        is_qualified=True,
        qualification_signals={"interest_level": "high", "next_steps": "Send estimate"},
        source="inbound_sms",
        last_appointment_status="completed",
        last_engaged_at=now,
        created_at=now,
        updated_at=now,
    )
    result = MagicMock()
    result.scalars.return_value.all.return_value = [contact]
    db = AsyncMock()
    db.execute.return_value = result
    executor = CRMToolExecutor(db=db, workspace_id=uuid.uuid4(), user_id=1)

    response = await executor.execute("search_contacts", {"query": "Ava", "limit": 5})

    evidence = response["data"][0]
    assert evidence["lead_score"] == 88
    assert evidence["engagement_score"] == 73
    assert evidence["qualification_signals"]["next_steps"] == "Send estimate"
    assert evidence["last_engaged_at"] == now.isoformat()
    assert evidence["updated_at"] == now.isoformat()


def _contact(contact_id: int) -> SimpleNamespace:
    now = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
    return SimpleNamespace(
        id=contact_id,
        first_name="Alex",
        last_name="Kim",
        phone_number=f"+1555000{contact_id:04d}",
        email=f"alex{contact_id}@example.com",
        status="lead",
        company_name="Example Co",
        lead_score=10,
        engagement_score=20,
        is_qualified=False,
        qualification_signals={},
        source="website",
        last_appointment_status=None,
        last_engaged_at=now,
        created_at=now,
        updated_at=now,
    )


def _snapshot_mock(
    *,
    timeline: list[dict[str, object]],
    offset: int = 0,
    limit: int = 20,
    has_more: bool = False,
    payload: dict[str, object] | None = None,
) -> MagicMock:
    observed_at = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
    snapshot = MagicMock()
    snapshot.observed_at = observed_at
    snapshot.recent_timeline = tuple(timeline)
    snapshot.timeline_offset = offset
    snapshot.timeline_limit = limit
    snapshot.timeline_has_more = has_more
    snapshot.model_dump.return_value = payload or {
        "contact_id": 512,
        "observed_at": observed_at.isoformat(),
        "recent_timeline": timeline,
        "timeline_offset": offset,
        "timeline_limit": limit,
        "timeline_has_more": has_more,
    }
    snapshot.render.return_value = "CONTACT CONTEXT SNAPSHOT\nAUTHORITY: structured state wins"
    return snapshot


@pytest.mark.asyncio
async def test_search_contacts_marks_ambiguous_names_for_identity_resolution() -> None:
    db = AsyncMock()
    db.scalar.return_value = 2
    result_proxy = MagicMock()
    result_proxy.scalars.return_value.all.return_value = [_contact(701), _contact(702)]
    db.execute.return_value = result_proxy
    executor = CRMToolExecutor(db=db, workspace_id=uuid.uuid4(), user_id=42)

    result = await executor.execute("search_contacts", {"query": "Alex Kim"})

    assert result["success"] is True
    assert result["returned"] == 2
    assert result["identity_resolution"] == {
        "status": "ambiguous",
        "candidate_count": 2,
        "next_action": (
            "Ask the operator to choose a candidate; do not guess or call "
            "get_contact_context until one contact_id is confirmed."
        ),
    }


@pytest.mark.asyncio
async def test_get_contact_context_returns_full_bounded_cross_channel_timeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timeline = [
        {
            "message_id": str(uuid.uuid4()),
            "channel": ("sms", "voice", "voicemail")[index % 3],
            "occurred_at": f"2026-08-17T11:{index:02d}:00+00:00",
            "provenance": [{"updated_at": f"2026-08-17T11:{index:02d}:00+00:00"}],
        }
        for index in range(50)
    ]
    snapshot = _snapshot_mock(timeline=timeline, limit=50)
    init_calls: list[dict[str, int]] = []

    class SnapshotServiceStub:
        def __init__(self, _db: object, **kwargs: int) -> None:
            init_calls.append(kwargs)

        async def get_snapshot(self, **_kwargs: object) -> MagicMock:
            return snapshot

    monkeypatch.setattr(
        contact_tools_module,
        "ContactContextSnapshotService",
        SnapshotServiceStub,
    )
    executor = CRMToolExecutor(db=AsyncMock(), workspace_id=uuid.uuid4(), user_id=42)

    result = await executor.execute(
        "get_contact_context",
        {"contact_id": 512, "timeline_limit": 50},
    )

    assert result["success"] is True
    assert len(result["data"]["snapshot"]["recent_timeline"]) == 50
    assert result["data"]["timeline_page"] == {
        "offset": 0,
        "limit": 50,
        "returned": 50,
        "has_more": False,
        "next_offset": None,
    }
    assert init_calls == [{"timeline_limit": 50, "timeline_offset": 0}]


@pytest.mark.asyncio
async def test_get_contact_context_preserves_current_state_and_stale_conflict_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload: dict[str, object] = {
        "contact_id": 512,
        "observed_at": "2026-08-17T12:00:00+00:00",
        "lifecycle": {
            "status": "qualified",
            "provenance": [{"updated_at": "2026-08-17T11:55:00+00:00"}],
        },
        "active_quotes": [
            {
                "status": "sent",
                "provenance": [{"updated_at": "2026-08-17T11:50:00+00:00"}],
            }
        ],
        "free_form_notes": [
            {
                "content": "Old note says quote declined",
                "provenance": [{"updated_at": "2026-07-01T09:00:00+00:00"}],
            }
        ],
        "recent_timeline": [],
    }
    snapshot = _snapshot_mock(timeline=[], payload=payload)

    class SnapshotServiceStub:
        def __init__(self, _db: object, **_kwargs: int) -> None:
            pass

        async def get_snapshot(self, **_kwargs: object) -> MagicMock:
            return snapshot

    monkeypatch.setattr(
        contact_tools_module,
        "ContactContextSnapshotService",
        SnapshotServiceStub,
    )
    executor = CRMToolExecutor(db=AsyncMock(), workspace_id=uuid.uuid4(), user_id=42)

    result = await executor.execute("get_contact_context", {"contact_id": 512})

    returned_snapshot = result["data"]["snapshot"]
    assert returned_snapshot["active_quotes"][0]["status"] == "sent"
    assert returned_snapshot["free_form_notes"][0]["content"] == "Old note says quote declined"
    assert (
        "structured fields override stale notes"
        in result["data"]["evidence_rules"]["state_precedence"]
    )
    assert "provenance.updated_at" in result["data"]["evidence_rules"]["response_requirement"]
    assert result["data"]["evidence_rules"]["untrusted_content_paths"] == [
        "snapshot.free_form_notes[*].content",
        "snapshot.recent_timeline[*].content",
    ]


@pytest.mark.asyncio
async def test_get_contact_context_pages_older_timeline_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timeline = [{"message_id": "older-1"}, {"message_id": "older-2"}]
    snapshot = _snapshot_mock(timeline=timeline, offset=20, limit=2, has_more=True)
    calls: list[dict[str, object]] = []

    class SnapshotServiceStub:
        def __init__(self, _db: object, **kwargs: int) -> None:
            calls.append({"init": kwargs})

        async def get_snapshot(self, **kwargs: object) -> MagicMock:
            calls.append({"get_snapshot": kwargs})
            return snapshot

    workspace_id = uuid.uuid4()
    monkeypatch.setattr(
        contact_tools_module,
        "ContactContextSnapshotService",
        SnapshotServiceStub,
    )
    executor = CRMToolExecutor(db=AsyncMock(), workspace_id=workspace_id, user_id=42)

    result = await executor.execute(
        "get_contact_context",
        {"contact_id": 512, "timeline_limit": 2, "timeline_offset": 20},
    )

    assert calls == [
        {"init": {"timeline_limit": 2, "timeline_offset": 20}},
        {"get_snapshot": {"workspace_id": workspace_id, "contact_id": 512}},
    ]
    assert result["data"]["timeline_page"] == {
        "offset": 20,
        "limit": 2,
        "returned": 2,
        "has_more": True,
        "next_offset": 22,
    }


@pytest.mark.asyncio
async def test_get_contact_context_denies_cross_workspace_contact_without_disclosure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested_scope: dict[str, object] = {}

    class SnapshotServiceStub:
        def __init__(self, _db: object, **_kwargs: int) -> None:
            pass

        async def get_snapshot(self, **kwargs: object) -> None:
            requested_scope.update(kwargs)

    workspace_id = uuid.uuid4()
    monkeypatch.setattr(
        contact_tools_module,
        "ContactContextSnapshotService",
        SnapshotServiceStub,
    )
    executor = CRMToolExecutor(db=AsyncMock(), workspace_id=workspace_id, user_id=42)

    result = await executor.execute("get_contact_context", {"contact_id": 9001})

    assert requested_scope == {"workspace_id": workspace_id, "contact_id": 9001}
    assert result["success"] is False
    assert result["code"] == "not_found"
    assert "other workspace" not in result["message"].lower()
    assert "data" not in result


@pytest.mark.asyncio
async def test_executor_error_telemetry_excludes_raw_pii() -> None:
    async def failing_handler(_args: dict[str, object]) -> dict[str, object]:
        raise RuntimeError("Customer jane.private@example.com at +15551234567")

    executor = CRMToolExecutor(db=AsyncMock(), workspace_id=uuid.uuid4(), user_id=42)
    executor.tool_metadata["pii_failure"] = CRMToolMetadata(
        name="pii_failure",
        handler=failing_handler,
        risk_level=ToolRiskLevel.LOW,
    )
    executor.log = MagicMock()

    result = await executor.execute(
        "pii_failure",
        {"email": "jane.private@example.com", "phone": "+15551234567"},
    )

    logged = repr(executor.log.error.call_args)
    assert "jane.private@example.com" not in logged
    assert "+15551234567" not in logged
    assert "email" in logged and "phone" in logged
    assert result["code"] == "internal"
