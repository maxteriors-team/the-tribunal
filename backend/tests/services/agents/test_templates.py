"""Tests for reusable agent templates."""

from app.schemas.agent import AgentCreate
from app.services.agents import (
    PRESTYJ_COLD_LEAD_RESPONDER_PROMPT,
    PRESTYJ_COLD_LEAD_RESPONDER_TEMPLATE_ID,
    build_prestyj_cold_lead_responder_template,
)


def test_prestyj_template_builds_agent_create_payload() -> None:
    """Template should return an AgentCreate-compatible payload."""
    template = build_prestyj_cold_lead_responder_template()

    assert isinstance(template, AgentCreate)
    assert PRESTYJ_COLD_LEAD_RESPONDER_TEMPLATE_ID == "prestyj_cold_lead_responder"
    assert template.name == "Prestyj Cold-Lead Responder"
    assert template.channel_mode == "text"
    assert template.temperature == 0.45
    assert template.text_response_delay_ms == 30_000
    assert template.text_max_context_messages == 24


def test_prestyj_template_prompt_covers_required_sales_workflow() -> None:
    """Prompt should cover cold replies, qualification, starter offer, and handoff."""
    template = build_prestyj_cold_lead_responder_template()
    prompt = template.system_prompt

    normalized_prompt = " ".join(prompt.split())
    required_phrases = [
        "Batch Video Ads",
        "cold or neutral",
        "$497 starter",
        "qualifying questions",
        "Objection handling",
        "Warm/high-intent handoff triggers",
        "Do not guarantee",
        "stop selling",
    ]

    for phrase in required_phrases:
        assert phrase in normalized_prompt

    assert prompt == PRESTYJ_COLD_LEAD_RESPONDER_PROMPT


def test_prestyj_template_enables_expected_tools_and_settings() -> None:
    """Template should enable tools in fields already used by the Agent model."""
    template = build_prestyj_cold_lead_responder_template()

    assert template.enabled_tools == [
        "web_search",
        "book_appointment",
        "human_handoff",
        "crm_update",
    ]
    assert template.tool_settings == {
        "calendar": ["check_availability", "book_appointment"],
        "crm": ["update_contact", "tag_contact", "create_opportunity"],
        "handoff": ["warm_lead", "high_intent", "human_review"],
        "messaging": ["sms", "chat"],
    }
