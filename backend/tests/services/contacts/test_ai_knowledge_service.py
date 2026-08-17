"""Operator-facing contact AI knowledge projection tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.ai.contact_ai_memory_service import (
    ContactMemoryContext,
    ContactMemoryFactContext,
)
from app.services.ai.contact_context_snapshot import ContextProvenance
from app.services.contacts.ai_knowledge_service import ContactAIKnowledgeService


def _provenance(source: str, observed_at: datetime) -> tuple[ContextProvenance, ...]:
    return (
        ContextProvenance(
            source=source,
            source_id="internal-record-id",
            observed_at=observed_at,
            updated_at=observed_at,
        ),
    )


@pytest.mark.asyncio
async def test_projection_exposes_bounded_state_and_generated_memory_without_contact_pii() -> None:
    observed_at = datetime(2026, 8, 17, 12, tzinfo=UTC)
    provenance = _provenance("contacts", observed_at)
    workspace_id = uuid.uuid4()
    fact_id = uuid.uuid4()
    snapshot = SimpleNamespace(
        workspace_id=workspace_id,
        contact_id=42,
        observed_at=observed_at,
        identity=SimpleNamespace(
            full_name="Private Person",
            email="private.person@example.com",
            phone_number="+15125550199",
            address=SimpleNamespace(line1="901 Private Lane"),
        ),
        lifecycle=SimpleNamespace(
            status="qualified",
            engagement_score=82,
            sms_consent_status="opted_in",
            provenance=provenance,
        ),
        qualification=SimpleNamespace(
            is_qualified=True,
            lead_score=91,
            signals={"private_note": "Do not expose"},
            provenance=provenance,
        ),
        tags=(SimpleNamespace(name="Fall service", provenance=provenance),),
        campaigns=(),
        open_opportunities=(
            SimpleNamespace(
                pipeline_name="Sales",
                stage_name="Quoted",
                status="open",
                amount=987654,
                provenance=provenance,
            ),
        ),
        active_quotes=(),
        active_invoices=(),
        upcoming_appointments=(
            SimpleNamespace(
                service_type="Gutter cleaning",
                status="confirmed",
                scheduled_at=observed_at + timedelta(days=2),
                provenance=provenance,
            ),
        ),
        latest_appointment=None,
        recent_timeline=(SimpleNamespace(content="Raw private conversation"),),
        free_form_notes=(SimpleNamespace(content="Raw operator note"),),
    )
    memory = ContactMemoryContext(
        summary="x" * 1200,
        summary_source_event_id="sms:conversation:message",
        summary_observed_at=observed_at - timedelta(days=1),
        facts=(
            ContactMemoryFactContext(
                fact_type="contact.status",
                value="new",
                confidence=0.8,
                provenance_event_id="sms:conversation:message",
                provenance_message_id=uuid.uuid4(),
                observed_at=observed_at - timedelta(days=1),
                expires_at=observed_at + timedelta(days=30),
                fact_id=fact_id,
                source_record_type="conversation",
            ),
        ),
    )

    with (
        patch(
            "app.services.contacts.ai_knowledge_service.ContactContextSnapshotService.get_snapshot",
            new=AsyncMock(return_value=snapshot),
        ),
        patch(
            "app.services.contacts.ai_knowledge_service.ContactAIMemoryService.get_context",
            new=AsyncMock(return_value=memory),
        ),
    ):
        result = await ContactAIKnowledgeService(MagicMock()).get_knowledge(
            workspace_id=workspace_id,
            contact_id=42,
        )

    assert result is not None
    assert result.next_action is not None
    assert result.next_action.value == "Prepare for upcoming gutter cleaning appointment"
    assert result.memory_summary is not None
    assert result.memory_summary.source == "AI from SMS"
    assert len(result.memory_summary.value) == 1000
    assert result.memory_facts[0].id == fact_id
    assert result.conflicts[0].authoritative_value == "Qualified"
    assert result.conflicts[0].generated_value == "new"

    serialized = result.model_dump_json()
    for private_value in (
        "Private Person",
        "private.person@example.com",
        "+15125550199",
        "901 Private Lane",
        "Do not expose",
        "987654",
        "Raw private conversation",
        "Raw operator note",
        "internal-record-id",
    ):
        assert private_value not in serialized


def test_authoritative_contact_memory_facts_are_not_operator_editable_items() -> None:
    observed_at = datetime(2026, 8, 17, 12, tzinfo=UTC)
    memory = ContactMemoryContext(
        summary=None,
        summary_source_event_id=None,
        summary_observed_at=None,
        facts=(
            ContactMemoryFactContext(
                fact_type="contact.note",
                value="CRM-authored note",
                confidence=1.0,
                provenance_event_id="contact-edit:event",
                provenance_message_id=None,
                observed_at=observed_at,
                expires_at=None,
                fact_id=uuid.uuid4(),
                source_record_type="contact",
            ),
        ),
    )

    # The filtering helper is exercised through the service-level projection test
    # above; this focused assertion documents the invariant at the context edge.
    from app.services.contacts.ai_knowledge_service import _memory_facts

    assert _memory_facts(memory) == []
