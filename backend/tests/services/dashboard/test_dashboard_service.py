"""Dashboard core-stat tests."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.workspace import Workspace
from app.services.dashboard.dashboard_service import DashboardService


def _scalar_result(value: int) -> MagicMock:
    result = MagicMock()
    result.scalar.return_value = value
    return result


@pytest.mark.asyncio
async def test_core_stats_counts_workspace_leads_in_trailing_24_hours() -> None:
    workspace_id = uuid.uuid4()
    contacts_result = MagicMock()
    contacts_result.one.return_value = (42, 7)
    db = AsyncMock()
    db.execute.side_effect = [
        contacts_result,
        _scalar_result(3),
        _scalar_result(6),
        _scalar_result(2),
        _scalar_result(4),
        _scalar_result(2),
        _scalar_result(5),
        _scalar_result(4),
        _scalar_result(100),
        _scalar_result(20),
        _scalar_result(10),
    ]
    workspace = Workspace(
        id=workspace_id,
        name="Daily dashboard",
        slug="daily-dashboard",
        settings={"timezone": "UTC"},
    )

    stats = await DashboardService(db).get_core_stats(workspace)

    assert stats.leads_last_24_hours == 7
    assert stats.total_contacts == 42

    contacts_query = db.execute.await_args_list[0].args[0]
    compiled = contacts_query.compile()
    query_params = compiled.params.values()
    cutoff = next(value for value in query_params if isinstance(value, datetime))
    elapsed = datetime.now(UTC) - cutoff

    assert workspace_id in query_params
    assert timedelta(hours=23, minutes=59) < elapsed < timedelta(hours=24, minutes=1)
    assert "contacts.workspace_id" in str(compiled)
    assert "contacts.created_at >=" in str(compiled)
