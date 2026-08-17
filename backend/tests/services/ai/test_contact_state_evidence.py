"""Structured tool evidence tests for mutable CRM claims."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from app.services.ai.contact_state_evidence import (
    build_contact_state_evidence,
    build_contact_state_not_found,
)

NOW = datetime(2026, 8, 17, 16, 0, tzinfo=UTC)


def test_live_evidence_includes_accepted_pending_quotes_and_existing_appointment() -> None:
    snapshot = SimpleNamespace(
        observed_at=NOW,
        identity=SimpleNamespace(full_name="Morgan Homeowner"),
        lifecycle=SimpleNamespace(status="qualified"),
        qualification=SimpleNamespace(
            is_qualified=True,
            qualified_at=NOW - timedelta(days=1),
            lead_score=92,
            signals={"service": "gutter cleaning", "property_type": "two story"},
        ),
        active_quotes=(
            SimpleNamespace(
                quote_id=uuid.uuid4(),
                number="Q-PENDING",
                title="Gutter proposal",
                status="sent",
                total=Decimal("450.00"),
                currency="USD",
                expiry_date=None,
                sent_at=NOW - timedelta(hours=3),
            ),
            SimpleNamespace(
                quote_id=uuid.uuid4(),
                number="Q-ACCEPTED",
                title="Roof wash proposal",
                status="approved",
                total=Decimal("900.00"),
                currency="USD",
                expiry_date=None,
                sent_at=NOW - timedelta(days=1),
            ),
        ),
        active_invoices=(),
        upcoming_appointments=(
            SimpleNamespace(
                appointment_id=41,
                status="scheduled",
                scheduled_at=NOW + timedelta(days=2),
                duration_minutes=60,
                service_type="Gutter cleaning",
            ),
        ),
        latest_appointment=None,
        recent_timeline=(
            SimpleNamespace(
                channel="voice",
                direction="inbound",
                occurred_at=NOW - timedelta(days=2),
                status="completed",
                content="Qualified during prior call for two-story gutter cleaning.",
                duration_seconds=240,
            ),
        ),
        free_form_notes=(
            SimpleNamespace(content="Stale note says quote Q-ACCEPTED is still pending."),
        ),
    )

    evidence = build_contact_state_evidence(snapshot)

    quote_states = {quote["number"]: quote["decision_state"] for quote in evidence["active_quotes"]}
    assert quote_states == {
        "Q-PENDING": "pending",
        "Q-ACCEPTED": "accepted",
    }
    assert evidence["domain_status"]["quote"] == "conflict"
    assert evidence["upcoming_appointments"][0]["appointment_id"] == 41
    assert evidence["contact"]["qualification_facts"]["property_type"] == "two story"
    assert evidence["recent_cross_channel_history"][0]["channel"] == "voice"
    assert "Stale note says" not in json.dumps(evidence)
    assert "override durable memory, notes" in evidence["message"]


def test_missing_live_record_is_explicitly_absent_not_inferred() -> None:
    evidence = build_contact_state_not_found(domains={"invoice"})

    assert evidence["success"] is True
    assert evidence["found"] is False
    assert evidence["domain_status"] == {"invoice": "absent"}
    assert evidence["evidence_status"] == "absent"
    assert "Do not use notes or prior messages as proof" in evidence["message"]
