"""Approval execution for outbound improvement pending actions."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.models.pending_action import PendingAction
from app.services.approval.approval_gate_service import ApprovalGateService


@pytest.mark.asyncio
async def test_outbound_follow_up_suggestion_execution_acknowledges_recommendation() -> None:
    service = ApprovalGateService()
    recommendation = {
        "title": "Follow up with reactivated leads",
        "message": "Want to book a consult?",
    }
    action = PendingAction(
        id=uuid4(),
        workspace_id=uuid4(),
        agent_id=None,
        action_type="outbound_improvement.follow_up_campaign",
        action_payload={"recommended_campaign": recommendation},
        description="Review outbound recommendation",
        context={
            "source": "outbound_improvement_suggestions",
            "dedupe_key": "outbound_improvement_suggestions:abc123",
        },
        status="approved",
    )

    result = await service._dispatch_action(None, action)  # type: ignore[arg-type]

    assert result == {
        "status": "acknowledged",
        "recommendation": recommendation,
        "source": "outbound_improvement_suggestions",
        "dedupe_key": "outbound_improvement_suggestions:abc123",
    }
