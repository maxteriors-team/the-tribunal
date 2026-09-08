"""Tests for the CRM assistant's reporting, pricing, queue and growth tools.

These tools are read-only, so the properties worth asserting are about *who sees
what* and *what is not disclosed*, plus one structural risk specific to this
batch: several handlers project ORM rows field by field. A wrong column name
there is invisible to mypy and to any test built on ``MagicMock`` (which happily
invents attributes), so the queue and lead-magnet tests below construct **real**
model instances -- a renamed or missing column fails them.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.roles import WorkspaceRole
from app.models.human_nudge import HumanNudge
from app.models.lead_magnet import LeadMagnet
from app.models.pending_action import PendingAction
from app.services.ai.crm_assistant._tool_executor import CRMToolExecutor
from app.services.ai.crm_assistant._tools import get_crm_tools, tools_for_role

OWNER = WorkspaceRole.OWNER.value
MANAGER = WorkspaceRole.MANAGER.value
SALES_REP = WorkspaceRole.SALES_REP.value
MEMBER = WorkspaceRole.MEMBER.value

NEW_TOOLS = {
    "get_report",
    "get_scorecard",
    "list_catalog_items",
    "list_inventory_items",
    "list_pending_actions",
    "list_nudges",
    "list_upsell_jobs",
    "list_referral_partners",
    "list_lead_magnets",
}


@pytest.fixture
def workspace_id() -> uuid.UUID:
    return uuid.uuid4()


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def unique(self) -> _Result:
        return self

    def scalars(self) -> _Result:
        return self

    def all(self) -> list[Any]:
        return self._rows

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None


@pytest.fixture
def db() -> MagicMock:
    session = MagicMock()
    session.execute = AsyncMock(return_value=_Result([]))
    session.scalar = AsyncMock(return_value=0)
    session.get = AsyncMock(return_value=MagicMock())
    return session


def _executor(db: MagicMock, workspace_id: uuid.UUID, role: str = OWNER) -> CRMToolExecutor:
    return CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7, role=role)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_every_new_tool_is_declared_and_needs_no_approval() -> None:
    from app.services.ai.crm_assistant._tool_metadata import get_tool_policy

    declared = {tool["function"]["name"] for tool in get_crm_tools()}
    assert declared >= NEW_TOOLS
    for name in NEW_TOOLS:
        assert get_tool_policy(name).requires_approval is False, name


# ---------------------------------------------------------------------------
# Capability tiering: each tool matches the capability its own route requires
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("role", "tool"),
    [
        (MANAGER, "get_report"),  # reports:view is admin-tier
        (MANAGER, "get_scorecard"),
        (SALES_REP, "list_catalog_items"),  # billing:read
        (SALES_REP, "get_report"),
    ],
)
async def test_tools_refuse_roles_below_their_capability(
    db: MagicMock, workspace_id: uuid.UUID, role: str, tool: str
) -> None:
    result = await _executor(db, workspace_id, role).execute(tool, {})

    assert result["success"] is False
    assert result["code"] == "not_permitted"


def test_manager_is_not_offered_report_tools() -> None:
    offered = {tool["function"]["name"] for tool in tools_for_role(MANAGER)}
    assert "get_report" not in offered
    assert "get_scorecard" not in offered
    # ...but the operational surfaces are theirs.
    assert offered >= {"list_catalog_items", "list_pending_actions", "list_nudges"}


# ---------------------------------------------------------------------------
# Disclosure: unit costs follow billing access, not job access
# ---------------------------------------------------------------------------


async def test_inventory_costs_are_withheld_below_billing_access(
    db: MagicMock, workspace_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`list_inventory_items` mirrors `_can_see_costs` on the inventory router."""
    captured: dict[str, Any] = {}

    async def fake_list_items(_self: Any, _ws: uuid.UUID, **kwargs: Any) -> Any:
        captured.update(kwargs)
        return MagicMock(items=[], total=0)

    monkeypatch.setattr(
        "app.services.inventory.inventory_service.InventoryService.list_items", fake_list_items
    )

    result = await _executor(db, workspace_id, MEMBER).execute("list_inventory_items", {})
    assert captured["include_costs"] is False
    assert result["costs_included"] is False

    await _executor(db, workspace_id, OWNER).execute("list_inventory_items", {})
    assert captured["include_costs"] is True


# ---------------------------------------------------------------------------
# Nudges are personal work, not the team's queue
# ---------------------------------------------------------------------------


async def test_nudge_visibility_matches_the_route_rule(
    db: MagicMock, workspace_id: uuid.UUID
) -> None:
    """crm:write additionally sees unassigned rows; a plain member does not."""
    member_sql = _nudge_sql(db, workspace_id, MEMBER)
    owner_sql = _nudge_sql(db, workspace_id, OWNER)

    assert "assigned_to_user_id IS NULL" not in member_sql
    assert "assigned_to_user_id IS NULL" in owner_sql
    # Both remain workspace-scoped.
    assert "workspace_id" in member_sql and "workspace_id" in owner_sql


def _nudge_sql(db: MagicMock, workspace_id: uuid.UUID, role: str) -> str:
    from sqlalchemy import select

    from app.services.ai.crm_assistant._queue_tools import QueueAssistantTools

    tools = QueueAssistantTools(MagicMock(db=db, workspace_id=workspace_id, user_id=7, role=role))
    stmt = select(HumanNudge).where(tools._nudge_visibility())
    return str(stmt.compile(compile_kwargs={"literal_binds": True}))


# ---------------------------------------------------------------------------
# Real ORM rows: catch a column name that does not exist
# ---------------------------------------------------------------------------


async def test_list_nudges_projects_real_columns(db: MagicMock, workspace_id: uuid.UUID) -> None:
    nudge = HumanNudge(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        contact_id=101,
        nudge_type="followup",
        title="Call Dana back",
        message="m" * 900,
        suggested_action="call",
        priority="high",
        status="pending",
        due_date=date(2026, 5, 4),
        assigned_to_user_id=7,
        created_at=datetime(2026, 5, 1, tzinfo=UTC),
    )
    db.execute = AsyncMock(return_value=_Result([nudge]))
    db.scalar = AsyncMock(return_value=1)

    result = await _executor(db, workspace_id).execute("list_nudges", {})

    row = result["data"][0]
    assert row["title"] == "Call Dana back"
    assert row["suggested_action"] == "call"
    assert row["due_date"] == "2026-05-04"
    assert len(row["message"]) == 500  # bounded


async def test_list_pending_actions_never_returns_the_drafted_payload(
    db: MagicMock, workspace_id: uuid.UUID
) -> None:
    """The parked message body stays in the app, where a human approves it."""
    action = PendingAction(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        action_type="send_sms",
        description="Text Dana about Tuesday",
        action_payload={"body": "SECRET DRAFT never shown to the model"},
        status="pending",
        urgency="normal",
        created_at=datetime(2026, 5, 1, tzinfo=UTC),
    )
    db.execute = AsyncMock(return_value=_Result([action]))
    db.scalar = AsyncMock(return_value=1)

    result = await _executor(db, workspace_id).execute("list_pending_actions", {})

    row = result["data"][0]
    assert row["action_type"] == "send_sms"
    assert row["urgency"] == "normal"
    assert "action_payload" not in row
    assert "SECRET DRAFT" not in str(result)


async def test_list_lead_magnets_projects_real_columns(
    db: MagicMock, workspace_id: uuid.UUID
) -> None:
    magnet = LeadMagnet(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        name="Gutter checklist",
        magnet_type="pdf",
        is_active=True,
        created_at=datetime(2026, 5, 1, tzinfo=UTC),
    )
    db.execute = AsyncMock(return_value=_Result([magnet]))
    db.scalar = AsyncMock(return_value=1)

    result = await _executor(db, workspace_id).execute("list_lead_magnets", {})

    assert result["data"][0]["name"] == "Gutter checklist"
    assert result["data"][0]["magnet_type"] == "pdf"


# ---------------------------------------------------------------------------
# Report dispatch argument handling
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tool", "args", "hint"),
    [
        ("get_report", {}, "report"),
        ("get_report", {"report": "made_up_report"}, "report"),
        ("get_report", {"report": "ar_aging", "date_to": "not-a-date"}, "date"),
        ("get_report", {"report": "cogs", "group_by": "nonsense"}, "group_by"),
        (
            "get_report",
            {"report": "sales_performance", "date_from": "2026-06-01", "date_to": "2026-01-01"},
            "date_from",
        ),
        ("get_scorecard", {"team": "everyone"}, "team"),
        ("list_catalog_items", {"limit": 0}, "limit"),
        ("list_catalog_items", {"search": 5}, "search"),
        ("list_nudges", {"limit": True}, "limit"),
        ("list_referral_partners", {"active_only": "yes"}, "active_only"),
    ],
)
async def test_bad_arguments_are_rejected_before_any_query(
    db: MagicMock, workspace_id: uuid.UUID, tool: str, args: dict[str, Any], hint: str
) -> None:
    result = await _executor(db, workspace_id).execute(tool, args)

    assert result["success"] is False
    assert result["code"] == "invalid_argument"
    assert hint in (result["message"] + result.get("hint", "")).lower()
    db.execute.assert_not_awaited()


async def test_scorecard_window_is_bounded(db: MagicMock, workspace_id: uuid.UUID) -> None:
    """A multi-year scan the route would refuse must not be reachable here."""
    result = await _executor(db, workspace_id).execute(
        "get_scorecard", {"team": "office_reps", "date_from": "2020-01-01", "date_to": "2026-01-01"}
    )

    assert result["success"] is False
    assert result["code"] == "invalid_argument"


async def test_get_report_dispatches_to_the_named_report(
    db: MagicMock, workspace_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    ar_aging = AsyncMock(return_value=MagicMock(model_dump=lambda mode: {"total_outstanding": 42}))
    monkeypatch.setattr(
        "app.services.reporting.reporting_service.ReportingService.ar_aging", ar_aging
    )

    result = await _executor(db, workspace_id).execute(
        "get_report", {"report": "ar_aging", "date_to": "2026-05-01"}
    )

    assert result["success"] is True
    assert result["report"] == "ar_aging"
    assert result["data"]["total_outstanding"] == 42
    assert ar_aging.await_args.kwargs["as_of"] == date(2026, 5, 1)
