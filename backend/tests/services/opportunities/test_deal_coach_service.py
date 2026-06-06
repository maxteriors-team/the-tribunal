"""Unit tests for the Deal Coach deterministic logic.

These cover the pure scoring/synthesis helpers (no DB / no OpenAI) that back
both the single coaching card's fallback and the at-risk ranking.
"""

from __future__ import annotations

from app.schemas.deal_coach import DealSignals
from app.services.opportunities.deal_coach_service import (
    _build_drafted_action,
    _heuristic_card,
    _parse_llm_card,
    _sentiment_trend,
    assess_risk,
)


def _assess(**overrides: object):
    base: dict[str, object] = {
        "days_since_last_contact": 1,
        "days_in_stage": 2,
        "engagement_score": 60,
        "lead_score": 60,
        "last_sentiment": "positive",
        "awaiting_reply": False,
        "objections": [],
        "expected_close_overdue": False,
    }
    base.update(overrides)
    return assess_risk(**base)  # type: ignore[arg-type]


class TestAssessRisk:
    def test_healthy_deal_low_risk(self) -> None:
        result = _assess()
        assert result.health == "healthy"
        assert result.risk_score < 25
        assert result.health_score == 100 - result.risk_score

    def test_silent_champion_flags_critical(self) -> None:
        result = _assess(days_since_last_contact=14, awaiting_reply=True)
        assert "Champion silent 14 days" in result.top_risk
        assert result.health in ("at_risk", "critical")
        assert result.risk_score >= 45

    def test_negative_sentiment_increases_risk(self) -> None:
        positive = _assess(last_sentiment="positive")
        negative = _assess(last_sentiment="negative")
        assert negative.risk_score > positive.risk_score

    def test_stalled_stage_is_a_factor(self) -> None:
        result = _assess(days_in_stage=40)
        assert any("Stalled" in f for f in result.risk_factors)

    def test_score_is_clamped_0_100(self) -> None:
        result = _assess(
            days_since_last_contact=90,
            days_in_stage=120,
            engagement_score=0,
            lead_score=0,
            last_sentiment="negative",
            awaiting_reply=True,
            objections=["too expensive"],
            expected_close_overdue=True,
        )
        assert 0 <= result.risk_score <= 100
        assert result.health == "critical"

    def test_no_engagement_yet_penalized(self) -> None:
        result = _assess(days_since_last_contact=None)
        assert result.top_risk == "No recorded engagement yet"


class TestSentimentTrend:
    def test_unknown_when_single(self) -> None:
        from datetime import UTC, datetime

        now = datetime.now(UTC)
        assert _sentiment_trend([(now, "positive")]) == "unknown"

    def test_improving_and_declining(self) -> None:
        from datetime import UTC, datetime, timedelta

        t0 = datetime.now(UTC)
        t1 = t0 + timedelta(days=1)
        assert _sentiment_trend([(t0, "negative"), (t1, "positive")]) == "improving"
        assert _sentiment_trend([(t0, "positive"), (t1, "negative")]) == "declining"
        assert _sentiment_trend([(t0, "neutral"), (t1, "neutral")]) == "flat"


class TestHeuristicCard:
    def test_objection_drives_offer_action(self) -> None:
        signals = DealSignals(objections=["price too high"], last_call_sentiment="negative")
        assessment = assess_risk(
            days_since_last_contact=2,
            days_in_stage=2,
            engagement_score=50,
            lead_score=50,
            last_sentiment="negative",
            awaiting_reply=False,
            objections=["price too high"],
            expected_close_overdue=False,
        )
        card = _heuristic_card(contact_name="Jane Doe", signals=signals, assessment=assessment)
        assert card.next_best_action.channel == "offer"
        assert "price too high" in card.drafted_action.body
        assert card.drafted_action.action_type == "deal_coach.follow_up"

    def test_silent_champion_drives_sms(self) -> None:
        signals = DealSignals(days_since_last_contact=10, awaiting_reply=True)
        assessment = assess_risk(
            days_since_last_contact=10,
            days_in_stage=3,
            engagement_score=50,
            lead_score=50,
            last_sentiment=None,
            awaiting_reply=True,
            objections=[],
            expected_close_overdue=False,
        )
        card = _heuristic_card(contact_name="Bob", signals=signals, assessment=assessment)
        assert card.next_best_action.channel == "sms"
        assert "Bob" in card.drafted_action.body

    def test_card_has_required_fields(self) -> None:
        signals = DealSignals()
        assessment = assess_risk(
            days_since_last_contact=1,
            days_in_stage=1,
            engagement_score=80,
            lead_score=80,
            last_sentiment="positive",
            awaiting_reply=False,
            objections=[],
            expected_close_overdue=False,
        )
        card = _heuristic_card(contact_name=None, signals=signals, assessment=assessment)
        assert card.deal_health in ("healthy", "watch", "at_risk", "critical")
        assert 0 <= card.health_score <= 100
        assert card.health_summary
        assert card.next_best_action.title
        assert card.drafted_action.body


class TestParseLlmCard:
    def test_invalid_values_fall_back_to_heuristic(self) -> None:
        signals = DealSignals(days_since_last_contact=10, awaiting_reply=True)
        assessment = assess_risk(
            days_since_last_contact=10,
            days_in_stage=3,
            engagement_score=50,
            lead_score=50,
            last_sentiment=None,
            awaiting_reply=True,
            objections=[],
            expected_close_overdue=False,
        )
        parsed = _parse_llm_card(
            {
                "deal_health": "not-a-status",
                "health_score": "oops",
                "next_best_action": {"channel": "carrier-pigeon"},
                "drafted_action": {"body": ""},
            },
            signals=signals,
            assessment=assessment,
        )
        assert parsed.deal_health == assessment.health
        assert parsed.health_score == assessment.health_score
        assert parsed.next_best_action.channel == "sms"
        # Empty body backfilled from heuristic so the draft is never blank.
        assert parsed.drafted_action.body

    def test_valid_llm_payload_preserved(self) -> None:
        signals = DealSignals()
        assessment = assess_risk(
            days_since_last_contact=1,
            days_in_stage=1,
            engagement_score=80,
            lead_score=80,
            last_sentiment="positive",
            awaiting_reply=False,
            objections=[],
            expected_close_overdue=False,
        )
        parsed = _parse_llm_card(
            {
                "deal_health": "watch",
                "health_score": 62,
                "health_summary": "Solid but quiet.",
                "top_risk": "champion silent 4 days",
                "risk_factors": ["quiet"],
                "next_best_action": {
                    "title": "Nudge",
                    "rationale": "re-open thread",
                    "channel": "sms",
                    "timing": "Today",
                },
                "drafted_action": {
                    "channel": "sms",
                    "description": "SMS nudge",
                    "body": "Hi there!",
                },
            },
            signals=signals,
            assessment=assessment,
        )
        assert parsed.deal_health == "watch"
        assert parsed.health_score == 62
        assert parsed.next_best_action.title == "Nudge"
        assert parsed.drafted_action.body == "Hi there!"


class TestBuildDraftedAction:
    def test_unknown_channel_defaults_to_sms(self) -> None:
        draft = _build_drafted_action(contact_name="X", channel="bogus", body="b", description="d")
        assert draft.channel == "sms"
        assert draft.payload == {"channel": "sms", "body": "b"}
