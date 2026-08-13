"""Validation tests for website-lead qualification agent settings."""

import pytest
from pydantic import ValidationError

from app.schemas.agent import AgentUpdate


def test_agent_update_normalizes_qualification_policy() -> None:
    update = AgentUpdate(
        tool_settings={
            "calendar": ["book_appointment"],
            "website_lead_qualification_enabled": True,
            "qualification_questions": ["  What service?  ", "", "What timeline?"],
            "qualification_min_score": 75,
            "qualification_booking_label": " Zoom estimate ",
        }
    )

    assert update.tool_settings == {
        "calendar": ["book_appointment"],
        "website_lead_qualification_enabled": True,
        "qualification_questions": ["What service?", "What timeline?"],
        "qualification_min_score": 75,
        "qualification_booking_label": "Zoom estimate",
    }


@pytest.mark.parametrize(
    "settings",
    [
        {"website_lead_qualification_enabled": "yes"},
        {"qualification_questions": ["question"] * 11},
        {"qualification_questions": ["x" * 201]},
        {"qualification_min_score": -1},
        {"qualification_min_score": 101},
        {"qualification_booking_label": "   "},
    ],
)
def test_agent_update_rejects_invalid_qualification_policy(settings: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        AgentUpdate(tool_settings=settings)


def test_agent_update_policy_is_off_by_default_without_settings() -> None:
    update = AgentUpdate(tool_settings={"calendar": ["book_appointment"]})

    assert update.tool_settings == {"calendar": ["book_appointment"]}
    assert update.tool_settings.get("website_lead_qualification_enabled", False) is False
