"""Bounded live-CRM evidence returned by contact lookup tools.

The serializer intentionally excludes free-form notes and durable memory. Those are useful
conversation context, but they are historical and must never override the typed CRM rows used
for quote, invoice, or appointment claims.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import Any, Final, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.services.ai.contact_context_snapshot import ContactContextSnapshot

type ContactEvidenceDomain = Literal["opportunity", "quote", "invoice", "appointment"]

ALL_CONTACT_EVIDENCE_DOMAINS: Final[frozenset[ContactEvidenceDomain]] = frozenset(
    {"opportunity", "quote", "invoice", "appointment"}
)
_MAX_HISTORY_ITEMS: Final = 8


def build_contact_state_evidence(
    snapshot: ContactContextSnapshot,
    *,
    domains: Collection[ContactEvidenceDomain] | None = None,
    timezone: str = "America/New_York",
) -> dict[str, Any]:
    """Return exact, JSON-safe contact evidence for a model tool result."""
    requested = frozenset(domains or ALL_CONTACT_EVIDENCE_DOMAINS)
    zone = _timezone(timezone)

    opportunities = [
        {
            "opportunity_id": str(opportunity.opportunity_id),
            "name": opportunity.name,
            "status": opportunity.status,
            "pipeline_id": str(opportunity.pipeline_id),
            "pipeline_name": opportunity.pipeline_name,
            "stage_id": str(opportunity.stage_id) if opportunity.stage_id else None,
            "stage_name": opportunity.stage_name,
            "amount": str(opportunity.amount),
            "currency": opportunity.currency,
            "probability": opportunity.probability,
            "expected_close_date": (
                opportunity.expected_close_date.isoformat()
                if opportunity.expected_close_date
                else None
            ),
        }
        for opportunity in getattr(snapshot, "open_opportunities", ())
    ]
    quotes = [
        {
            "quote_id": str(quote.quote_id),
            "number": quote.number,
            "title": quote.title,
            "status": quote.status,
            "decision_state": _quote_decision_state(quote.status),
            "total": str(quote.total),
            "currency": quote.currency,
            "expiry_date": quote.expiry_date.isoformat() if quote.expiry_date else None,
            "sent_at": quote.sent_at.isoformat() if quote.sent_at else None,
        }
        for quote in snapshot.active_quotes
    ]
    invoices = [
        {
            "invoice_id": str(invoice.invoice_id),
            "number": invoice.number,
            "status": invoice.status,
            "total": str(invoice.total),
            "amount_paid": str(invoice.amount_paid),
            "balance_due": str(invoice.balance_due),
            "currency": invoice.currency,
            "due_date": invoice.due_date.isoformat() if invoice.due_date else None,
            "sent_at": invoice.sent_at.isoformat() if invoice.sent_at else None,
        }
        for invoice in snapshot.active_invoices
    ]
    upcoming_appointments = [
        _appointment_evidence(appointment, zone) for appointment in snapshot.upcoming_appointments
    ]
    latest_appointment = (
        _appointment_evidence(snapshot.latest_appointment, zone)
        if snapshot.latest_appointment is not None
        else None
    )

    domain_status: dict[str, str] = {}
    if "opportunity" in requested:
        domain_status["opportunity"] = _record_status(len(opportunities))
    if "quote" in requested:
        domain_status["quote"] = _record_status(len(quotes))
    if "invoice" in requested:
        domain_status["invoice"] = _record_status(len(invoices))
    if "appointment" in requested:
        appointment_count = len(upcoming_appointments) or int(latest_appointment is not None)
        domain_status["appointment"] = _record_status(appointment_count)

    result: dict[str, Any] = {
        "success": True,
        "found": True,
        "evidence_source": "live_crm",
        "observed_at": snapshot.observed_at.isoformat(),
        "requested_domains": sorted(requested),
        "evidence_domains": sorted(requested),
        "domain_status": domain_status,
        "evidence_status": _combined_status(domain_status),
        "contact": {
            "name": snapshot.identity.full_name,
            "status": snapshot.lifecycle.status,
            "is_qualified": snapshot.qualification.is_qualified,
            "qualified_at": (
                snapshot.qualification.qualified_at.isoformat()
                if snapshot.qualification.qualified_at
                else None
            ),
            "lead_score": snapshot.qualification.lead_score,
            "qualification_facts": snapshot.qualification.signals,
        },
        "recent_cross_channel_history": [
            {
                "channel": item.channel,
                "direction": item.direction,
                "occurred_at": item.occurred_at.isoformat(),
                "status": item.status,
                "content": item.content,
                "duration_seconds": item.duration_seconds,
            }
            for item in snapshot.recent_timeline[-_MAX_HISTORY_ITEMS:]
        ],
        "message": (
            "These fields were read from the live CRM for this contact just now. "
            "They override durable memory, notes, training examples, and prior messages. "
            "For any requested domain marked absent or conflict, ask one focused question "
            "or hand off; do not infer which record or value the customer means."
        ),
    }
    if "opportunity" in requested:
        result["current_opportunities"] = opportunities
    if "quote" in requested:
        result["active_quotes"] = quotes
    if "invoice" in requested:
        result["active_invoices"] = invoices
    if "appointment" in requested:
        result["upcoming_appointments"] = upcoming_appointments
        result["latest_appointment"] = latest_appointment
    return result


def build_contact_state_not_found(
    *,
    domains: Collection[ContactEvidenceDomain] | None = None,
) -> dict[str, Any]:
    """Return a safe result when the bound contact cannot be resolved."""
    requested = sorted(domains or ALL_CONTACT_EVIDENCE_DOMAINS)
    return {
        "success": True,
        "found": False,
        "evidence_source": "live_crm",
        "requested_domains": requested,
        "evidence_domains": requested,
        "domain_status": dict.fromkeys(requested, "absent"),
        "evidence_status": "absent",
        "message": (
            "No live CRM record was found for this contact. Do not use notes or prior "
            "messages as proof of an opportunity, qualification, price, quote, invoice, "
            "or appointment. Ask one "
            "focused question or hand off to a human."
        ),
    }


def _appointment_evidence(appointment: Any, zone: ZoneInfo) -> dict[str, Any]:
    local_time = appointment.scheduled_at.astimezone(zone)
    return {
        "appointment_id": appointment.appointment_id,
        "status": appointment.status,
        "scheduled_at": local_time.isoformat(),
        "when": local_time.strftime("%A, %B %d at %I:%M %p"),
        "duration_minutes": appointment.duration_minutes,
        "service_type": appointment.service_type,
    }


def _quote_decision_state(status: str) -> str:
    if status == "approved":
        return "accepted"
    if status == "sent":
        return "pending"
    return status


def _record_status(record_count: int) -> str:
    if record_count == 0:
        return "absent"
    if record_count == 1:
        return "found"
    return "conflict"


def _combined_status(domain_status: dict[str, str]) -> str:
    statuses = set(domain_status.values())
    if not statuses or statuses == {"absent"}:
        return "absent"
    if statuses == {"found"}:
        return "found"
    if statuses == {"conflict"}:
        return "conflict"
    return "mixed"


def _timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("America/New_York")
