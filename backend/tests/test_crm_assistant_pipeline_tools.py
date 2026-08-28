"""Focused coverage for CRM assistant pipeline and stage discovery."""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from app.models.pipeline import Pipeline, PipelineStage
from app.services.ai.crm_assistant._tool_executor import CRMToolExecutor
from app.services.ai.crm_assistant._tools import get_crm_tools


class _ExecuteResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows


def _pipeline(workspace_id: uuid.UUID, *, name: str = "Sales Pipeline") -> Pipeline:
    return Pipeline(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        name=name,
        description=None,
        is_active=True,
    )


def _stage(
    pipeline_id: uuid.UUID,
    *,
    name: str,
    order: int,
    probability: int,
) -> PipelineStage:
    return PipelineStage(
        id=uuid.uuid4(),
        pipeline_id=pipeline_id,
        name=name,
        description=None,
        order=order,
        probability=probability,
        stage_type="active",
    )


async def test_list_pipeline_stages_returns_pipeline_and_stage_ids_in_order() -> None:
    workspace_id = uuid.uuid4()
    pipeline = _pipeline(workspace_id)
    new_lead = _stage(pipeline.id, name="New Lead", order=0, probability=10)
    qualified = _stage(pipeline.id, name="Qualified", order=1, probability=40)
    db = MagicMock()
    db.execute = AsyncMock(
        return_value=_ExecuteResult([(pipeline, new_lead), (pipeline, qualified)])
    )
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7, role="owner")

    result = await executor.execute("list_pipeline_stages", {})

    assert result == {
        "success": True,
        "data": [
            {
                "pipeline_id": str(pipeline.id),
                "pipeline_name": "Sales Pipeline",
                "pipeline_is_active": True,
                "stage_id": str(new_lead.id),
                "stage_name": "New Lead",
                "stage_order": 0,
                "stage_type": "active",
                "stage_probability": 10,
            },
            {
                "pipeline_id": str(pipeline.id),
                "pipeline_name": "Sales Pipeline",
                "pipeline_is_active": True,
                "stage_id": str(qualified.id),
                "stage_name": "Qualified",
                "stage_order": 1,
                "stage_type": "active",
                "stage_probability": 40,
            },
        ],
        "returned": 2,
        "total": 2,
        "has_more": False,
    }

    statement = db.execute.await_args.args[0]
    sql = str(statement.compile()).lower()
    assert "order by pipelines.name asc" in sql
    assert 'pipeline_stages."order" asc' in sql


async def test_list_pipeline_stages_filters_names_and_scopes_workspace() -> None:
    workspace_id = uuid.uuid4()
    db = MagicMock()
    db.execute = AsyncMock(return_value=_ExecuteResult([]))
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7, role="owner")

    result = await executor.execute(
        "list_pipeline_stages",
        {"pipeline_name": "Perm Light", "stage_name": "New Lead"},
    )

    assert result["success"] is True
    assert result["data"] == []
    statement = db.execute.await_args.args[0]
    compiled = statement.compile()
    sql = str(compiled).lower()
    params = set(compiled.params.values())
    assert "join pipeline_stages" in sql
    assert "pipelines.workspace_id" in sql
    assert workspace_id in params
    assert "%Perm Light%" in params
    assert "%New Lead%" in params


def test_list_pipeline_stages_registry_schema_exposes_optional_name_filters() -> None:
    schema = next(
        tool["function"]
        for tool in get_crm_tools()
        if tool["function"]["name"] == "list_pipeline_stages"
    )

    assert schema["parameters"]["properties"] == {
        "pipeline_name": {
            "type": "string",
            "description": "Optional pipeline name filter",
        },
        "stage_name": {
            "type": "string",
            "description": "Optional stage name filter",
        },
    }
    assert "required" not in schema["parameters"]
