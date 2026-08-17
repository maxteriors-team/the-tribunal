"""Data-minimized operator projection of contact context and generated AI memory.

The full :class:`ContactContextSnapshot` contains direct identifiers, notes, and
message text needed by AI callers. This projection intentionally exposes only
bounded CRM state plus generated memory; it never serializes identity, address,
raw timeline, notes, record IDs, or financial amounts.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, date, datetime, time

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.contact import (
    ContactAIKnowledgeConflict,
    ContactAIKnowledgeNextAction,
    ContactAIKnowledgeResponse,
    ContactAIKnowledgeStructuredFact,
    ContactAIMemoryFact,
    ContactAIMemorySummary,
)
from app.services.ai.contact_ai_memory_service import (
    MAX_CONTEXT_FACTS,
    ContactAIMemoryService,
    ContactMemoryContext,
    ContactMemoryFactContext,
)
from app.services.ai.contact_context_snapshot import (
    ContactContextSnapshot,
    ContactContextSnapshotService,
    ContextProvenance,
)

_MAX_STRUCTURED_FACTS = 10
_MAX_TAGS_SHOWN = 5
_MAX_MEMORY_SUMMARY_CHARS = 1000
_FACT_LABELS = {
    "appointment.outcome": "Appointment outcome",
    "budget": "Budget context",
    "commitment": "Commitment",
    "contact.objection": "Objection",
    "conversation.intent": "Conversation intent",
    "conversation.outcome": "Conversation outcome",
    "next_step": "Next step",
    "preference": "Preference",
    "service_interest": "Service interest",
    "timing": "Timing",
}
_NORMALIZE_VALUE_RE = re.compile(r"[\s_-]+")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _date_as_utc(value: date | None) -> datetime | None:
    if value is None:
        return None
    return datetime.combine(value, time.min, tzinfo=UTC)


def _provenance_time(
    provenance: tuple[ContextProvenance, ...],
    fallback: datetime,
) -> datetime:
    if not provenance:
        return _as_utc(fallback)
    return max(_as_utc(item.updated_at or item.observed_at) for item in provenance)


def _display_value(value: object) -> str:
    return str(getattr(value, "value", value)).replace("_", " ").strip().title()


def _fact_label(fact_type: str) -> str:
    if fact_type in _FACT_LABELS:
        return _FACT_LABELS[fact_type]
    return fact_type.replace(".", " ").replace("_", " ").strip().title()


def _memory_source(event_id: str | None, source_record_type: str | None = None) -> str:
    normalized_event = (event_id or "").lower()
    if source_record_type == "operator" or normalized_event.startswith("operator:"):
        return "Operator correction"
    if source_record_type == "voice_message" or normalized_event.startswith(("call", "voice")):
        return "AI from voice call"
    if source_record_type == "conversation" or normalized_event.startswith("sms:"):
        return "AI from SMS"
    return "AI-generated memory"


def _structured_facts(snapshot: ContactContextSnapshot) -> list[ContactAIKnowledgeStructuredFact]:
    facts: list[ContactAIKnowledgeStructuredFact] = []

    def add(
        key: str,
        label: str,
        value: str | None,
        source: str,
        provenance: tuple[ContextProvenance, ...],
    ) -> None:
        cleaned = (value or "").strip()
        if not cleaned or len(facts) >= _MAX_STRUCTURED_FACTS:
            return
        facts.append(
            ContactAIKnowledgeStructuredFact(
                key=key,
                label=label,
                value=cleaned[:500],
                source=source,
                observed_at=_provenance_time(provenance, snapshot.observed_at),
            )
        )

    lifecycle = snapshot.lifecycle
    add(
        "contact_status",
        "Contact status",
        _display_value(lifecycle.status),
        "CRM contact record",
        lifecycle.provenance,
    )
    qualification_value = (
        f"{'Qualified' if snapshot.qualification.is_qualified else 'Not qualified'}"
        f" · score {snapshot.qualification.lead_score}/100"
    )
    add(
        "qualification",
        "Qualification",
        qualification_value,
        "CRM qualification fields",
        snapshot.qualification.provenance,
    )
    add(
        "sms_consent",
        "SMS permission",
        _display_value(lifecycle.sms_consent_status),
        "CRM consent record",
        lifecycle.provenance,
    )

    if snapshot.tags:
        tag_names = [tag.name for tag in snapshot.tags[:_MAX_TAGS_SHOWN]]
        remaining = len(snapshot.tags) - len(tag_names)
        tag_value = ", ".join(tag_names)
        if remaining > 0:
            tag_value += f" +{remaining} more"
        add(
            "tags",
            "Tags",
            tag_value,
            "CRM tags",
            tuple(item for tag in snapshot.tags for item in tag.provenance),
        )

    if lifecycle.engagement_score > 0:
        add(
            "engagement",
            "Engagement",
            f"{lifecycle.engagement_score}/100",
            "CRM engagement score",
            lifecycle.provenance,
        )

    if snapshot.campaigns:
        campaign = snapshot.campaigns[0]
        add(
            "campaign",
            "Campaign",
            f"{campaign.name} · {_display_value(campaign.enrollment_status)}",
            "CRM campaign enrollment",
            campaign.provenance,
        )

    if snapshot.open_opportunities:
        opportunity = snapshot.open_opportunities[0]
        stage = opportunity.stage_name or _display_value(opportunity.status)
        add(
            "pipeline",
            "Pipeline",
            f"{opportunity.pipeline_name} · {stage}",
            "CRM opportunity",
            opportunity.provenance,
        )

    if snapshot.upcoming_appointments:
        appointment = snapshot.upcoming_appointments[0]
        service = appointment.service_type or "Service"
        add(
            "appointment",
            "Upcoming appointment",
            f"{service} · {_display_value(appointment.status)}",
            "CRM appointment",
            appointment.provenance,
        )

    if snapshot.active_quotes:
        quote = snapshot.active_quotes[0]
        add(
            "quote",
            "Active quote",
            _display_value(quote.status),
            "CRM quote",
            quote.provenance,
        )

    if snapshot.active_invoices:
        invoice = snapshot.active_invoices[0]
        add(
            "invoice",
            "Active invoice",
            _display_value(invoice.status),
            "CRM invoice",
            invoice.provenance,
        )

    return facts


def _next_action(snapshot: ContactContextSnapshot) -> ContactAIKnowledgeNextAction | None:
    overdue_invoice = next(
        (invoice for invoice in snapshot.active_invoices if invoice.status == "overdue"),
        None,
    )
    if overdue_invoice is not None:
        return ContactAIKnowledgeNextAction(
            value="Resolve overdue invoice",
            due_at=_date_as_utc(overdue_invoice.due_date),
            source="CRM invoice",
            observed_at=_provenance_time(overdue_invoice.provenance, snapshot.observed_at),
        )

    if snapshot.upcoming_appointments:
        appointment = min(snapshot.upcoming_appointments, key=lambda item: item.scheduled_at)
        service = appointment.service_type or "service"
        service = service[:1].lower() + service[1:]
        return ContactAIKnowledgeNextAction(
            value=f"Prepare for upcoming {service} appointment",
            due_at=_as_utc(appointment.scheduled_at),
            source="CRM appointment",
            observed_at=_provenance_time(appointment.provenance, snapshot.observed_at),
        )

    campaigns_with_follow_up = [
        campaign
        for campaign in snapshot.campaigns
        if campaign.next_follow_up_at is not None and not campaign.opted_out
    ]
    if campaigns_with_follow_up:
        campaign = min(
            campaigns_with_follow_up,
            key=lambda item: item.next_follow_up_at or datetime.max.replace(tzinfo=UTC),
        )
        due_at = campaign.next_follow_up_at
        assert due_at is not None
        return ContactAIKnowledgeNextAction(
            value=f"Continue {campaign.name} follow-up",
            due_at=_as_utc(due_at),
            source="CRM campaign enrollment",
            observed_at=_provenance_time(campaign.provenance, snapshot.observed_at),
        )

    sent_quote = next((quote for quote in snapshot.active_quotes if quote.status == "sent"), None)
    if sent_quote is not None:
        return ContactAIKnowledgeNextAction(
            value="Follow up on active quote",
            due_at=_date_as_utc(sent_quote.expiry_date),
            source="CRM quote",
            observed_at=_provenance_time(sent_quote.provenance, snapshot.observed_at),
        )

    if snapshot.open_opportunities:
        opportunity = snapshot.open_opportunities[0]
        stage = opportunity.stage_name or "current stage"
        return ContactAIKnowledgeNextAction(
            value=f"Advance opportunity from {stage}",
            source="CRM opportunity",
            observed_at=_provenance_time(opportunity.provenance, snapshot.observed_at),
        )

    return None


def _authoritative_values(snapshot: ContactContextSnapshot) -> dict[str, tuple[str, str]]:
    values: dict[str, tuple[str, str]] = {
        "contact.status": ("Contact status", _display_value(snapshot.lifecycle.status)),
        "contact.qualification_status": (
            "Qualification",
            "Qualified" if snapshot.qualification.is_qualified else "Not qualified",
        ),
        "contact.qualification_score": (
            "Qualification score",
            str(snapshot.qualification.lead_score),
        ),
    }
    if snapshot.upcoming_appointments:
        values["appointment.status"] = (
            "Appointment status",
            _display_value(snapshot.upcoming_appointments[0].status),
        )
    if snapshot.active_quotes:
        values["quote.status"] = (
            "Quote status",
            _display_value(snapshot.active_quotes[0].status),
        )
    if snapshot.active_invoices:
        values["invoice.status"] = (
            "Invoice status",
            _display_value(snapshot.active_invoices[0].status),
        )
    if snapshot.open_opportunities:
        values["opportunity.status"] = (
            "Opportunity status",
            _display_value(snapshot.open_opportunities[0].status),
        )
    return values


def _normalized_comparison(value: str) -> str:
    return _NORMALIZE_VALUE_RE.sub(" ", value.strip().casefold())


def _conflicts(
    snapshot: ContactContextSnapshot,
    facts: list[ContactAIMemoryFact],
) -> list[ContactAIKnowledgeConflict]:
    authoritative = _authoritative_values(snapshot)
    conflicts: list[ContactAIKnowledgeConflict] = []
    for fact in facts:
        current = authoritative.get(fact.fact_type)
        if current is None:
            continue
        label, authoritative_value = current
        if _normalized_comparison(fact.value) == _normalized_comparison(authoritative_value):
            continue
        conflicts.append(
            ContactAIKnowledgeConflict(
                fact_id=fact.id,
                label=label,
                generated_value=fact.value,
                authoritative_value=authoritative_value,
                message="CRM is current and takes priority over generated memory.",
            )
        )
    return conflicts


def _memory_fact(item: ContactMemoryFactContext) -> ContactAIMemoryFact | None:
    if item.fact_id is None or item.source_record_type == "contact":
        return None
    return ContactAIMemoryFact(
        id=item.fact_id,
        fact_type=item.fact_type,
        label=_fact_label(item.fact_type),
        value=item.value,
        confidence=item.confidence,
        source=_memory_source(item.provenance_event_id, item.source_record_type),
        observed_at=_as_utc(item.observed_at),
        expires_at=_as_utc(item.expires_at) if item.expires_at is not None else None,
    )


def _memory_facts(memory: ContactMemoryContext) -> list[ContactAIMemoryFact]:
    return [fact for item in memory.facts if (fact := _memory_fact(item)) is not None]


class ContactAIKnowledgeService:
    """Build a tenant-scoped operator projection from snapshot-first contact context."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_knowledge(
        self,
        *,
        workspace_id: uuid.UUID,
        contact_id: int,
    ) -> ContactAIKnowledgeResponse | None:
        snapshot = await ContactContextSnapshotService(
            self._db,
            timeline_limit=1,
        ).get_snapshot(workspace_id=workspace_id, contact_id=contact_id)
        if snapshot is None:
            return None

        memory = await ContactAIMemoryService(self._db).get_context(
            workspace_id=workspace_id,
            contact_id=contact_id,
            now=snapshot.observed_at,
            limit=MAX_CONTEXT_FACTS,
        )
        memory_facts = _memory_facts(memory) if memory is not None else []
        memory_summary = None
        if memory is not None and memory.summary and memory.summary_observed_at is not None:
            memory_summary = ContactAIMemorySummary(
                value=memory.summary[:_MAX_MEMORY_SUMMARY_CHARS],
                source=_memory_source(memory.summary_source_event_id),
                observed_at=_as_utc(memory.summary_observed_at),
            )

        return ContactAIKnowledgeResponse(
            contact_id=contact_id,
            generated_at=_as_utc(snapshot.observed_at),
            structured_facts=_structured_facts(snapshot),
            next_action=_next_action(snapshot),
            memory_summary=memory_summary,
            memory_facts=memory_facts,
            conflicts=_conflicts(snapshot, memory_facts),
        )
