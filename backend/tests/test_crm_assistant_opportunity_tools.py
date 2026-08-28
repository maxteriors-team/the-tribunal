"""CRM assistant opportunity creation, updates, and owner visibility."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.ai.crm_assistant._tool_executor import CRMToolExecutor
from app.services.ai.crm_assistant._tools import get_crm_tools


class _Result:
    def __init__(self, row: object | None) -> None:
        self.row = row

    def scalar_one_or_none(self) -> object | None:
        return self.row


@pytest.fixture
def workspace_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def db() -> MagicMock:
    session = MagicMock()
    session.execute = AsyncMock()
    return session


def _response(**data: object) -> MagicMock:
    response = MagicMock()
    for key, value in data.items():
        setattr(response, key, value)
    response.model_dump.return_value = {"id": str(uuid.uuid4()), **data}
    return response


def test_opportunity_write_tools_are_strictly_declared() -> None:
    tools = {tool["function"]["name"]: tool["function"] for tool in get_crm_tools()}

    assert {"get_opportunity", "create_opportunity", "update_opportunity"}.issubset(tools)
    assert tools["create_opportunity"]["parameters"]["required"] == ["pipeline_id", "name"]
    assert "opportunity_id" in tools["update_opportunity"]["parameters"]["required"]
    assert "delete_opportunity" not in tools


@pytest.mark.parametrize(
    ("role", "expected_owner"),
    [("sales_rep", 7), ("manager", None)],
)
async def test_list_opportunities_applies_role_owner_scope(
    db: MagicMock,
    workspace_id: uuid.UUID,
    role: str,
    expected_owner: int | None,
) -> None:
    page = SimpleNamespace(items=[], total=0)
    list_opportunities = AsyncMock(return_value=page)
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7, role=role)

    with patch(
        "app.services.ai.crm_assistant._opportunity_tools.OpportunityService.list_opportunities",
        list_opportunities,
    ):
        result = await executor.execute("list_opportunities", {"limit": 25})

    assert result["success"] is True
    assert list_opportunities.await_args.kwargs["restrict_to_user_id"] == expected_owner


@pytest.mark.parametrize(
    ("role", "expected_owner"),
    [("sales_rep", 7), ("manager", None)],
)
async def test_get_opportunity_applies_role_owner_scope(
    db: MagicMock,
    workspace_id: uuid.UUID,
    role: str,
    expected_owner: int | None,
) -> None:
    opportunity_id = uuid.uuid4()
    get_opportunity = AsyncMock(return_value=_response(id=str(opportunity_id)))
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7, role=role)

    with patch(
        "app.services.ai.crm_assistant._opportunity_tools.OpportunityService.get_opportunity",
        get_opportunity,
    ):
        result = await executor.execute("get_opportunity", {"opportunity_id": str(opportunity_id)})

    assert result["success"] is True
    assert get_opportunity.await_args.kwargs["restrict_to_user_id"] == expected_owner


async def test_sales_create_is_forced_to_self_assignment(
    db: MagicMock, workspace_id: uuid.UUID
) -> None:
    pipeline_id = uuid.uuid4()
    create_opportunity = AsyncMock(return_value=_response(name="Roof replacement"))
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7, role="sales_rep")

    with patch(
        "app.services.ai.crm_assistant._opportunity_tools.OpportunityService.create_opportunity",
        create_opportunity,
    ):
        result = await executor.execute(
            "create_opportunity",
            {
                "pipeline_id": str(pipeline_id),
                "name": "Roof replacement",
                "assigned_user_id": 999,
                "amount": 12_000,
            },
        )

    assert result["success"] is True
    assert create_opportunity.await_args.kwargs["assigned_user_id"] == 7


async def test_sales_update_stays_owner_scoped_and_self_assigned(
    db: MagicMock, workspace_id: uuid.UUID
) -> None:
    opportunity_id = uuid.uuid4()
    pipeline_id = uuid.uuid4()
    get_opportunity = AsyncMock(return_value=_response(pipeline_id=pipeline_id))
    update_opportunity = AsyncMock(return_value=_response(name="Updated"))
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7, role="sales_rep")

    with (
        patch(
            "app.services.ai.crm_assistant._opportunity_tools.OpportunityService.get_opportunity",
            get_opportunity,
        ),
        patch(
            "app.services.ai.crm_assistant._opportunity_tools.OpportunityService.update_opportunity",
            update_opportunity,
        ),
    ):
        result = await executor.execute(
            "update_opportunity",
            {
                "opportunity_id": str(opportunity_id),
                "name": "Updated",
                "assigned_user_id": 999,
            },
        )

    assert result["success"] is True
    assert get_opportunity.await_args.kwargs["restrict_to_user_id"] == 7
    assert update_opportunity.await_args.args[3] == 7
    assert update_opportunity.await_args.kwargs["restrict_to_user_id"] == 7


async def test_create_rejects_stage_outside_workspace_or_pipeline(
    db: MagicMock, workspace_id: uuid.UUID
) -> None:
    db.execute.return_value = _Result(None)
    create_opportunity = AsyncMock()
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7, role="manager")

    with patch(
        "app.services.ai.crm_assistant._opportunity_tools.OpportunityService.create_opportunity",
        create_opportunity,
    ):
        result = await executor.execute(
            "create_opportunity",
            {
                "pipeline_id": str(uuid.uuid4()),
                "stage_id": str(uuid.uuid4()),
                "name": "Foreign stage",
            },
        )

    assert result["code"] == "not_found"
    compiled = str(db.execute.await_args.args[0].compile(compile_kwargs={"literal_binds": True}))
    assert "pipelines.workspace_id" in compiled
    assert workspace_id.hex in compiled
    create_opportunity.assert_not_awaited()
