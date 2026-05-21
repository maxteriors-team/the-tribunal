"""Tests for outbound improvement suggestion generation helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.models.campaign_report import CampaignReport
from app.services.ai.outbound_improvement_suggestion_service import (
    CampaignEvidence,
    OutboundImprovementSuggestionService,
    OutboundRecommendation,
    PeriodWindow,
    build_dedupe_key,
    build_pending_action_payload,
    extract_best_campaign,
    extract_best_message,
    extract_best_segment,
    parse_llm_recommendation,
    safe_rate,
    summarize_best_performers,
)


def make_evidence(
    *,
    campaign_id=None,  # type: ignore[no-untyped-def]
    report_id=None,  # type: ignore[no-untyped-def]
    name: str = "Campaign A",
    agent_id=None,  # type: ignore[no-untyped-def]
    total_contacts: int = 100,
    appointments_booked: int = 10,
    contacts_qualified: int = 20,
    replies_received: int = 30,
    segment: str = "Past no-shows",
    segment_score: float = 0.4,
) -> CampaignEvidence:
    return CampaignEvidence(
        campaign_id=campaign_id or uuid4(),
        report_id=report_id or uuid4(),
        campaign_name=name,
        campaign_type="sms",
        responder_agent_id=agent_id,
        initial_message=f"Initial message for {name}",
        sms_fallback_template=None,
        metrics={
            "total_contacts": total_contacts,
            "messages_sent": total_contacts,
            "appointments_booked": appointments_booked,
            "contacts_qualified": contacts_qualified,
            "replies_received": replies_received,
        },
        recommendations=[{"recommendation": "Repeat the consult-first angle"}],
        segment_analysis=[{"segment": segment, "conversion_rate": segment_score}],
        timing_analysis={"best_time": "Tuesday morning", "response_rate": 0.25},
        prompt_performance=[{"version_id": str(uuid4()), "success_rate": 0.33}],
        key_findings=[{"finding": "Consult-first copy outperformed discounts"}],
        what_worked=[{"angle": "Consult-first"}],
    )


def test_safe_rate_handles_zero_denominator() -> None:
    assert safe_rate(10, 0) == 0.0
    assert safe_rate(None, 10) == 0.0
    assert safe_rate(2, 4) == 0.5


def test_best_performer_extraction_prefers_highest_observed_rates() -> None:
    weaker = make_evidence(
        name="Weak",
        appointments_booked=1,
        contacts_qualified=2,
        segment_score=0.1,
    )
    stronger = make_evidence(
        name="Strong",
        appointments_booked=20,
        contacts_qualified=30,
        segment="Reactivated leads",
        segment_score=0.7,
    )

    best_campaign = extract_best_campaign([weaker, stronger])
    best_segment = extract_best_segment([weaker, stronger])
    best_message = extract_best_message([weaker, stronger])

    assert best_campaign is not None
    assert best_campaign["name"] == "Strong"
    assert best_segment is not None
    assert best_segment["segment"] == "Reactivated leads"
    assert best_message is not None
    assert best_message["message"] == "Initial message for Strong"


def test_parse_llm_json_falls_back_on_malformed_response() -> None:
    fallback = OutboundRecommendation(
        title="Fallback",
        rationale="Fallback rationale",
        target_segment="Segment",
        angle="Angle",
        message="Message",
        responder_agent_id=None,
        confidence=0.6,
        expected_outcome="More replies",
    )

    assert parse_llm_recommendation("not json", fallback) == fallback

    parsed = parse_llm_recommendation(
        '{"title":"Parsed","confidence":2,"message":"New message"}', fallback
    )
    assert parsed.title == "Parsed"
    assert parsed.message == "New message"
    assert parsed.confidence == 1.0


def test_pending_action_payload_and_dedupe_context_shape() -> None:
    workspace_id = uuid4()
    evidence = [make_evidence()]
    window = PeriodWindow(
        name="daily",
        starts_at=datetime(2026, 5, 19, tzinfo=UTC),
        ends_at=datetime(2026, 5, 20, tzinfo=UTC),
    )
    summary = summarize_best_performers(evidence)
    recommendation = OutboundRecommendation(
        title="Follow up with reactivated leads",
        rationale="They booked most often.",
        target_segment="Reactivated leads",
        angle="Consult-first",
        message="Book a consult?",
        responder_agent_id=evidence[0].responder_agent_id,
        confidence=0.72,
        expected_outcome="More bookings",
    )

    payload = build_pending_action_payload(window, evidence, summary, recommendation)
    dedupe_key = build_dedupe_key(workspace_id, window, [evidence[0].report_id])

    assert payload["period"]["name"] == "daily"
    assert payload["source_campaign_ids"] == [str(evidence[0].campaign_id)]
    assert payload["source_report_ids"] == [str(evidence[0].report_id)]
    assert payload["recommended_campaign"]["title"] == "Follow up with reactivated leads"
    assert payload["confidence"] == 0.72
    assert dedupe_key.startswith("outbound_improvement_suggestions:")
    assert dedupe_key == build_dedupe_key(workspace_id, window, [evidence[0].report_id])


@pytest.mark.asyncio
async def test_dedupe_query_returns_true_when_matching_action_exists() -> None:
    service = OutboundImprovementSuggestionService()
    db = AsyncMock()
    result = SimpleNamespace(scalar_one_or_none=lambda: uuid4())
    db.execute.return_value = result

    exists = await service.pending_action_exists(db, uuid4(), "dedupe-key")

    assert exists is True
    db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_mark_reports_with_suggestion_appends_action_id() -> None:
    service = OutboundImprovementSuggestionService()
    report = CampaignReport(
        id=uuid4(),
        campaign_id=uuid4(),
        workspace_id=uuid4(),
        status="completed",
        generated_suggestion_ids=["existing"],
    )
    action_id = uuid4()
    scalars = SimpleNamespace(all=lambda: [report])
    result = SimpleNamespace(scalars=lambda: scalars)
    db = AsyncMock()
    db.execute.return_value = result

    await service.mark_reports_with_suggestion(db, [report.id], action_id)

    assert report.generated_suggestion_ids == ["existing", str(action_id)]
    db.flush.assert_awaited_once()
