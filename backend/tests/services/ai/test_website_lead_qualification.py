"""Policy and prompt tests for live website-lead qualification."""

import uuid
from types import SimpleNamespace

from app.services.ai.website_lead_qualification import (
    build_qualification_instructions,
    gate_website_lead_booking_tools,
    get_mark_lead_qualified_tool,
    get_website_lead_qualification_policy,
)


def _agent(*, enabled: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        tool_settings={
            "website_lead_qualification_enabled": enabled,
            "qualification_questions": ["What service?", "What timeline?"],
            "qualification_min_score": 70,
            "qualification_booking_label": "Zoom estimate",
        }
    )


def _contact(*, source: str = "lead_form", qualified: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        id=44,
        workspace_id=uuid.uuid4(),
        source=source,
        is_qualified=qualified,
        notes="Service: gutter cleaning\nAddress: 10 Main St",
    )


def test_policy_only_applies_to_enabled_website_form_leads() -> None:
    assert get_website_lead_qualification_policy(_agent(), _contact()) is not None
    assert get_website_lead_qualification_policy(_agent(enabled=False), _contact()) is None
    assert get_website_lead_qualification_policy(_agent(), _contact(source="manual")) is None


def test_instructions_use_form_context_and_require_one_question_at_a_time() -> None:
    contact = _contact()
    policy = get_website_lead_qualification_policy(_agent(), contact)
    assert policy is not None

    instructions = build_qualification_instructions(policy, contact=contact)

    assert "What service?" in instructions
    assert "gutter cleaning" in instructions
    assert "never re-ask" in instructions
    assert "exactly one missing checklist question per SMS" in instructions
    assert "do not offer times, links, availability, or booking yet" in instructions
    assert "Zoom estimate" in instructions
    assert "human will follow up" in instructions


def test_booking_tool_schemas_are_removed_until_persisted_qualification() -> None:
    pending_contact = _contact()
    qualified_contact = _contact(qualified=True)
    policy = get_website_lead_qualification_policy(_agent(), pending_contact)
    assert policy is not None
    booking_tools = [
        {"function": {"name": "book_appointment"}},
        {"function": {"name": "check_availability"}},
        {"function": {"name": "cancel_appointment"}},
    ]

    pending_names = [
        tool["function"]["name"]
        for tool in gate_website_lead_booking_tools(
            booking_tools, policy=policy, contact=pending_contact
        )
    ]
    qualified_names = [
        tool["function"]["name"]
        for tool in gate_website_lead_booking_tools(
            booking_tools, policy=policy, contact=qualified_contact
        )
    ]

    assert pending_names == ["cancel_appointment", "mark_lead_qualified"]
    assert qualified_names == ["book_appointment", "check_availability", "cancel_appointment"]


def test_mark_tool_requires_one_evidence_item_per_question() -> None:
    policy = get_website_lead_qualification_policy(_agent(), _contact())
    assert policy is not None

    parameters = get_mark_lead_qualified_tool(policy)["function"]["parameters"]

    assert parameters["properties"]["score"]["minimum"] == 0
    assert parameters["properties"]["criteria_evidence"]["minItems"] == 2
    assert parameters["properties"]["criteria_evidence"]["maxItems"] == 2
    assert parameters["additionalProperties"] is False
