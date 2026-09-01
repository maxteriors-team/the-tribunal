"""The deal installation endpoint requires pipeline and job write authority."""

from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from app.core.permissions import Capability
from app.main import app
from app.models.workspace import WorkspaceMembership


def _installation_gate() -> Any:
    path = "/api/v1/workspaces/{workspace_id}/opportunities/{opportunity_id}/installation-date"
    route = next(
        route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path == path and route.methods == {"PUT"}
    )

    expected = frozenset(
        {
            Capability.PIPELINE_WRITE_OWN,
            Capability.JOBS_WRITE,
        }
    )
    calls: list[Any] = []

    def walk(dependant: Any) -> None:
        call = getattr(dependant, "call", None)
        if getattr(call, "required_capabilities", None) == expected:
            calls.append(call)
        for child in dependant.dependencies:
            walk(child)

    walk(route.dependant)
    assert len(calls) == 1
    return calls[0]


@pytest.mark.asyncio
async def test_installation_gate_rejects_sales_and_allows_manager() -> None:
    gate = _installation_gate()
    sales = cast(WorkspaceMembership, SimpleNamespace(role="sales_rep"))
    manager = cast(WorkspaceMembership, SimpleNamespace(role="manager"))

    with pytest.raises(HTTPException) as exc_info:
        await gate(sales)
    assert exc_info.value.status_code == 403
    assert await gate(manager) is manager
