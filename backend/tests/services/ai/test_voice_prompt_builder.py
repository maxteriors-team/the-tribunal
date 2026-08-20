"""Focused voice prompt tests for live CRM evidence and cross-channel memory."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.ai import call_context as call_context_module
from app.services.ai.call_context import CallContext
from app.services.ai.contact_ai_memory_service import (
    ContactMemoryContext,
    ContactMemoryFactContext,
)
from app.services.ai.contact_context_snapshot import (
    ContactAppointmentContext,
    ContactAttributionContext,
    ContactContextSnapshot,
    ContactIdentityContext,
    ContactInvoiceContext,
    ContactLifecycleContext,
    ContactOpportunityContext,
    ContactQualificationContext,
    ContactQuoteContext,
    ContactTimelineItem,
    ContextProvenance,
)
from app.services.ai.contact_state_evidence import build_contact_state_evidence
from app.services.ai.elevenlabs_voice_agent import ElevenLabsVoiceAgentSession
from app.services.ai.grok.session_config import GrokSessionConfigBuilder
from app.services.ai.voice_agent import VoiceAgentSession
from app.services.ai.voice_prompt_builder import (
    CRM_EVIDENCE_POLICY,
    MAX_VOICE_CALL_CONTEXT_CHARS,
    VoicePromptBuilder,
    render_voice_contact_snapshot,
    render_voice_durable_memory,
    render_voice_recent_interactions,
    voice_context_requires_live_lookup,
)
from app.services.ai.voice_tools import get_tools_from_agent_config

NOW = datetime(2026, 8, 17, 16, 0, tzinfo=UTC)
WORKSPACE_ID = uuid.uuid4()
CONTACT_ID = 42


def test_voice_booking_prompt_requires_spoken_confirmation_turn() -> None:
    prompt = VoicePromptBuilder(timezone="America/Chicago").get_booking_instructions()

    assert "[VOICE BOOKING CONFIRMATION]" in prompt
    assert "exact weekday and calendar date" in prompt
    assert "America/Chicago timezone" in prompt
    assert "duration, and invite email" in prompt
    assert "stop speaking and wait" in prompt
    assert "customer_confirmed=true" in prompt


def _provenance(
    source: str,
    source_id: str,
    updated_at: datetime = NOW,
) -> tuple[ContextProvenance, ...]:
    return (
        ContextProvenance(
            source=source,
            source_id=source_id,
            observed_at=NOW,
            updated_at=updated_at,
        ),
    )


def _snapshot() -> ContactContextSnapshot:
    opportunity_id = uuid.uuid4()
    quote_id = uuid.uuid4()
    invoice_id = uuid.uuid4()
    pipeline_id = uuid.uuid4()
    sms_inbound_id = uuid.uuid4()
    sms_human_id = uuid.uuid4()
    contact_provenance = _provenance("contacts", str(CONTACT_ID), NOW - timedelta(days=2))
    return ContactContextSnapshot(
        workspace_id=WORKSPACE_ID,
        contact_id=CONTACT_ID,
        observed_at=NOW,
        identity=ContactIdentityContext(
            full_name="Jamie Rivera",
            phone_number="+15555550123",
            email="jamie@example.com",
            company_name="Rivera Homes",
            provenance=contact_provenance,
        ),
        lifecycle=ContactLifecycleContext(
            status="qualified",
            source="referral",
            created_at=NOW - timedelta(days=100),
            last_engaged_at=NOW - timedelta(hours=1),
            engagement_score=88,
            sms_consent_status="opted_in",
            sms_consent_source="web_form",
            sms_consent_collected_at=NOW - timedelta(days=100),
            email_opted_out_at=None,
            email_opt_out_source=None,
            no_show_count=0,
            last_appointment_status="scheduled",
            provenance=contact_provenance,
        ),
        qualification=ContactQualificationContext(
            is_qualified=True,
            qualified_at=NOW - timedelta(days=2),
            lead_score=91,
            signals={"service": "roof wash", "budget_confirmed": True},
            provenance=contact_provenance,
        ),
        attribution=ContactAttributionContext(
            source="referral",
            utm_source=None,
            utm_medium=None,
            utm_campaign=None,
            utm_content=None,
            utm_term=None,
            confidence=0.9,
            first_touch=None,
            latest_touch=None,
            source_campaign_id=None,
            source_campaign_name=None,
            referral_partner_id=None,
            referral_partner_name=None,
            provenance=contact_provenance,
        ),
        open_opportunities=(
            ContactOpportunityContext(
                opportunity_id=opportunity_id,
                name="Roof wash",
                status="open",
                pipeline_id=pipeline_id,
                pipeline_name="Residential",
                stage_id=uuid.uuid4(),
                stage_name="Quote accepted",
                amount=Decimal("850.00"),
                currency="USD",
                probability=90,
                expected_close_date=date(2026, 8, 20),
                provenance=_provenance("opportunities", str(opportunity_id)),
            ),
        ),
        active_quotes=(
            ContactQuoteContext(
                quote_id=quote_id,
                number="Q-1042",
                title="Roof wash proposal",
                status="accepted",
                total=Decimal("850.00"),
                currency="USD",
                issue_date=date(2026, 8, 14),
                expiry_date=date(2026, 9, 1),
                sent_at=NOW - timedelta(days=3),
                approved_at=NOW - timedelta(hours=2),
                deposit_paid_at=None,
                provenance=_provenance("quotes", str(quote_id)),
            ),
        ),
        active_invoices=(
            ContactInvoiceContext(
                invoice_id=invoice_id,
                number="INV-1042",
                status="partially_paid",
                total=Decimal("850.00"),
                amount_paid=Decimal("200.00"),
                balance_due=Decimal("650.00"),
                currency="USD",
                issue_date=date(2026, 8, 17),
                due_date=date(2026, 8, 24),
                sent_at=NOW - timedelta(hours=1),
                provenance=_provenance("invoices", str(invoice_id)),
            ),
        ),
        upcoming_appointments=(
            ContactAppointmentContext(
                appointment_id=9001,
                status="scheduled",
                scheduled_at=NOW + timedelta(days=2),
                duration_minutes=90,
                service_type="Roof wash",
                campaign_id=None,
                provenance=_provenance("appointments", "9001"),
            ),
        ),
        recent_timeline=(
            ContactTimelineItem(
                message_id=sms_inbound_id,
                channel="sms",
                direction="inbound",
                occurred_at=NOW - timedelta(hours=3),
                status="received",
                content="Can we move Thursday's appointment to Friday?",
                duration_seconds=None,
                is_ai=False,
                provenance=_provenance("messages", str(sms_inbound_id), NOW - timedelta(hours=3)),
            ),
            ContactTimelineItem(
                message_id=sms_human_id,
                channel="sms",
                direction="outbound",
                occurred_at=NOW - timedelta(hours=2),
                status="sent",
                content="A teammate is checking Friday availability for you.",
                duration_seconds=None,
                is_ai=False,
                provenance=_provenance("messages", str(sms_human_id), NOW - timedelta(hours=2)),
            ),
        ),
    )


def _agent_without_lookup() -> SimpleNamespace:
    return SimpleNamespace(
        enabled_tools=[],
        tool_settings={},
        transfer_destination_number=None,
    )


def test_returning_caller_prompt_preserves_campaign_offer_and_authority() -> None:
    snapshot = _snapshot()
    prompt = VoicePromptBuilder().build_context_section(
        contact_info={
            "contact_id": CONTACT_ID,
            "requires_live_crm_lookup": True,
            "name": "Jamie Rivera",
            "structured_context": render_voice_contact_snapshot(snapshot),
            "returning_summary": (
                "Prior voice summary: the quote was still pending and Thursday was final."
            ),
            "campaign_info": {
                "name": "August reactivation",
                "description": "Reconnect with past customers",
            },
        },
        offer_info={"name": "Returning customer wash", "discount_value": "10%"},
    )

    assert "August reactivation" in prompt
    assert "Returning customer wash" in prompt
    assert 'status="accepted"' in prompt
    assert "Authority order" in prompt
    assert prompt.index('status="accepted"') < prompt.index("quote was still pending")
    assert "Never treat these summaries as current evidence" not in prompt  # supplied legacy string
    assert "historical memory override live CRM data" in prompt


def test_cross_channel_continuity_labels_sms_contact_and_human_authorship() -> None:
    rendered = render_voice_recent_interactions(_snapshot())

    assert "move Thursday's appointment to Friday" in rendered
    assert '"actor":"contact"' in rendered
    assert '"actor":"human"' in rendered
    assert '"channel":"sms"' in rendered
    assert '"freshness":"today"' in rendered
    assert "source" in rendered and "observed_at" in rendered


def test_live_lookup_evidence_includes_current_opportunity_and_qualification() -> None:
    evidence = build_contact_state_evidence(_snapshot())

    assert evidence["contact"]["is_qualified"] is True
    assert evidence["current_opportunities"][0]["stage_name"] == "Quote accepted"
    assert evidence["current_opportunities"][0]["amount"] == "850.00"
    assert evidence["domain_status"]["opportunity"] == "found"


def test_rescheduling_requires_fresh_lookup_and_handoff() -> None:
    prompt = VoicePromptBuilder().build_context_section(
        contact_info={
            "contact_id": CONTACT_ID,
            "requires_live_crm_lookup": True,
            "structured_context": render_voice_contact_snapshot(_snapshot()),
        }
    )

    assert "lookup_caller_record" in prompt
    assert "check_availability" in prompt
    assert "There is no atomic voice reschedule tool" in prompt
    assert "do not cancel/rebook or claim it moved" in prompt
    assert "clarify and hand off" in prompt


def test_accepted_quote_live_record_outranks_stale_pending_memory() -> None:
    snapshot = _snapshot()
    stale_memory = ContactMemoryContext(
        summary="The quote is pending approval.",
        summary_source_event_id="summary-old",
        summary_observed_at=NOW - timedelta(days=120),
        facts=(
            ContactMemoryFactContext(
                fact_type="pricing_constraint",
                value="Quote Q-1042 was pending.",
                confidence=0.8,
                provenance_event_id="fact-old",
                provenance_message_id=uuid.uuid4(),
                observed_at=NOW - timedelta(days=30),
                expires_at=NOW + timedelta(days=2),
            ),
        ),
    )

    memory = render_voice_durable_memory(stale_memory, observed_at=NOW)
    prompt = VoicePromptBuilder().build_context_section(
        contact_info={
            "contact_id": CONTACT_ID,
            "requires_live_crm_lookup": True,
            "structured_context": render_voice_contact_snapshot(snapshot),
            "ai_memory_context": memory,
        }
    )

    assert 'status="accepted"' in prompt
    assert "summary_omitted=stale" in prompt
    assert "Q-1042 was pending" in prompt
    assert prompt.index('status="accepted"') < prompt.index("Q-1042 was pending")
    assert "durable cross-channel memory" in CRM_EVIDENCE_POLICY


def test_prompt_context_is_bounded_without_dropping_required_sections() -> None:
    prompt = VoicePromptBuilder().build_context_section(
        contact_info={
            "contact_id": CONTACT_ID,
            "requires_live_crm_lookup": True,
            "structured_context": "LIVE" * 10_000,
            "recent_interaction_context": "SMS" * 5_000,
            "ai_memory_context": "MEMORY" * 5_000,
            "returning_summary": "VOICE" * 5_000,
            "campaign_info": {"name": "Campaign", "description": "x" * 10_000},
        },
        offer_info={"name": "Offer", "terms": "y" * 10_000},
    )

    assert len(prompt) <= MAX_VOICE_CALL_CONTEXT_CHARS
    assert "CRM Evidence Policy" in prompt
    assert "Live ContactContextSnapshot" in prompt
    assert "Current Call Campaign" in prompt
    assert "Current Call Offer" in prompt
    assert "Recent Cross-Channel Interactions" in prompt
    assert "Durable Cross-Channel Memory" in prompt


def test_missing_contact_does_not_force_lookup_or_memory_policy() -> None:
    contact_info = {"lead_source_known": False}
    prompt = VoicePromptBuilder().build_context_section(contact_info=contact_info)

    assert voice_context_requires_live_lookup(contact_info) is False
    assert "lookup_caller_record" not in prompt
    assert "Durable Cross-Channel Memory" not in prompt


def test_known_contact_forces_read_only_lookup_tool_without_agent_opt_in() -> None:
    tools = get_tools_from_agent_config(
        _agent_without_lookup(),
        require_caller_record_lookup=True,
    )
    names = {tool.get("name") for tool in tools}

    assert "lookup_caller_record" in names


@pytest.mark.asyncio
async def test_openai_bridge_forces_live_crm_tool_during_context_update() -> None:
    session = VoiceAgentSession(api_key="test-key")
    send = AsyncMock()
    session.ws = SimpleNamespace(send=send)

    await session.inject_context(
        contact_info={
            "contact_id": CONTACT_ID,
            "requires_live_crm_lookup": True,
            "structured_context": "live snapshot",
        }
    )

    payload = json.loads(send.await_args.args[0])
    tool_names = {tool["name"] for tool in payload["session"]["tools"]}
    assert "lookup_caller_record" in tool_names
    assert "CRM Evidence Policy" in payload["session"]["instructions"]


def test_grok_and_elevenlabs_bridges_force_same_live_crm_tool() -> None:
    agent = _agent_without_lookup()
    grok_config = (
        GrokSessionConfigBuilder(agent, VoicePromptBuilder(agent))
        .with_tools(require_caller_record_lookup=True)
        .build()
    )
    grok_tool_names = {tool["name"] for tool in grok_config["tools"]}

    elevenlabs_session = ElevenLabsVoiceAgentSession(
        xai_api_key="test-xai",
        elevenlabs_api_key="test-elevenlabs",
        agent=agent,
    )
    elevenlabs_tool_names = {
        tool["name"]
        for tool in elevenlabs_session._build_grok_tools(  # noqa: SLF001 - bridge contract
            require_caller_record_lookup=True
        )
    }

    assert "lookup_caller_record" in grok_tool_names
    assert "lookup_caller_record" in elevenlabs_tool_names


@pytest.mark.asyncio
async def test_campaign_lookup_is_workspace_scoped() -> None:
    class _EmptyResult:
        def scalar_one_or_none(self) -> None:
            return None

    class _CapturingSession:
        def __init__(self) -> None:
            self.statement: object | None = None

        async def execute(self, statement: object) -> _EmptyResult:
            self.statement = statement
            return _EmptyResult()

    db = _CapturingSession()
    conversation = SimpleNamespace(id=uuid.uuid4(), workspace_id=WORKSPACE_ID)

    await call_context_module._attach_campaign_and_offer_context(
        db=db,
        context=CallContext(contact_info={"contact_id": CONTACT_ID}),
        conversation=conversation,
        log=SimpleNamespace(info=lambda *_args, **_kwargs: None),
    )

    assert db.statement is not None
    params = db.statement.compile().params
    assert WORKSPACE_ID in params.values()
    assert conversation.id in params.values()


@pytest.mark.asyncio
async def test_optional_contact_enrichment_has_hard_latency_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = CallContext(
        contact_info={
            "contact_id": CONTACT_ID,
            "campaign_info": {"name": "Preserved campaign"},
        },
        offer_info={"name": "Preserved offer"},
    )

    async def _slow_enrichment(**_kwargs: object) -> None:
        await asyncio.sleep(0.1)

    monkeypatch.setattr(
        call_context_module,
        "_attach_structured_contact_context_and_memory",
        _slow_enrichment,
    )
    returning = AsyncMock()
    monkeypatch.setattr(call_context_module, "_attach_returning_caller_context", returning)

    await call_context_module._attach_bounded_cross_channel_context(
        db=object(),
        context=context,
        workspace_id=WORKSPACE_ID,
        contact_id=CONTACT_ID,
        current_message_id=uuid.uuid4(),
        log=SimpleNamespace(warning=lambda *_args, **_kwargs: None),
        timeout_seconds=0.01,
    )

    assert context.metadata["contact_context_status"] == "timed_out"
    assert context.contact_info["campaign_info"]["name"] == "Preserved campaign"
    assert context.offer_info["name"] == "Preserved offer"
    returning.assert_not_awaited()
