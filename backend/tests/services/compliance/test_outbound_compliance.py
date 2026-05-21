"""Unit tests for ``OutboundComplianceService``.

The service runs every outbound SMS / campaign send through a stack of
gates:

* global opt-out (Redis-backed via :class:`OptOutManager`)
* SMS consent
* quiet-hours window (timezone-aware, with DST + invalid-tz fallback)
* per-campaign cumulative send cap
* per-contact send cap
* duplicate ``campaign_initial_sms`` guard

Each branch is exercised with light in-memory stand-ins for the SQLAlchemy
models so we don't need a live database. The duplicate-guard branch uses a
mock ``AsyncSession`` because that is the only path that issues a real
query.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.campaign import CampaignContactStatus
from app.services.compliance.outbound_compliance import (
    OutboundComplianceRequest,
    OutboundComplianceResult,
    OutboundComplianceService,
)

# --------------------------------------------------------------------------- #
# Fixtures / stand-ins
# --------------------------------------------------------------------------- #


@dataclass
class _StubCampaign:
    """Minimal stand-in for ``app.models.campaign.Campaign``.

    Only the attributes the service touches need to exist.
    """

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    max_messages_per_campaign: int | None = None
    max_messages_per_contact: int = 5
    messages_sent: int = 0
    quiet_hours_start: time | None = None
    quiet_hours_end: time | None = None
    quiet_hours_timezone: str | None = None
    timezone: str | None = None


@dataclass
class _StubCampaignContact:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    messages_sent: int = 0
    compliance_checked_at: datetime | None = None
    last_compliance_result: dict[str, Any] | None = None
    suppressed_reason: str | None = None
    suppressed_at: datetime | None = None
    status: CampaignContactStatus = CampaignContactStatus.PENDING
    opted_out: bool = False
    opted_out_at: datetime | None = None


@dataclass
class _StubContact:
    id: int = 1
    phone_number: str = "+15551234567"
    sms_consent_status: str | None = "opted_in"


def _build_request(
    *,
    contact: _StubContact | None = None,
    campaign_contact: _StubCampaignContact | None = None,
    campaign: _StubCampaign | None = None,
    channel: str = "sms",
    action_type: str = "campaign_initial_sms",
    now: datetime | None = None,
    require_sms_consent: bool = True,
) -> OutboundComplianceRequest:
    return OutboundComplianceRequest(
        workspace_id=uuid.uuid4(),
        campaign=campaign or _StubCampaign(),  # type: ignore[arg-type]
        campaign_contact=campaign_contact,  # type: ignore[arg-type]
        contact=contact or _StubContact(),  # type: ignore[arg-type]
        channel=channel,
        action_type=action_type,
        now=now or datetime(2026, 5, 21, 15, 0, tzinfo=UTC),
        require_sms_consent=require_sms_consent,
    )


@pytest.fixture
def opt_out_manager() -> MagicMock:
    """Default opt-out manager: nobody is opted out."""
    manager = MagicMock()
    manager.check_opt_out = AsyncMock(return_value=False)
    return manager


@pytest.fixture
def service(opt_out_manager: MagicMock) -> OutboundComplianceService:
    return OutboundComplianceService(opt_out_manager=opt_out_manager)


@pytest.fixture
def db_no_duplicate() -> AsyncMock:
    """AsyncSession stand-in whose duplicate query returns False."""
    db = AsyncMock()
    duplicate_result = MagicMock()
    duplicate_result.scalar.return_value = False
    db.execute = AsyncMock(return_value=duplicate_result)
    return db


@pytest.fixture
def db_with_duplicate() -> AsyncMock:
    """AsyncSession stand-in whose duplicate query returns True."""
    db = AsyncMock()
    duplicate_result = MagicMock()
    duplicate_result.scalar.return_value = True
    db.execute = AsyncMock(return_value=duplicate_result)
    return db


# --------------------------------------------------------------------------- #
# evaluate() — gate branches
# --------------------------------------------------------------------------- #


class TestEvaluateGates:
    """Every blocking gate must short-circuit before the next."""

    async def test_global_opt_out_blocks(
        self, service: OutboundComplianceService, opt_out_manager: MagicMock
    ) -> None:
        opt_out_manager.check_opt_out = AsyncMock(return_value=True)
        result = await service.evaluate(_build_request(), AsyncMock())
        assert result.allowed is False
        assert result.reason == "global_opt_out"

    async def test_missing_sms_consent_blocks(
        self, service: OutboundComplianceService
    ) -> None:
        contact = _StubContact(sms_consent_status="unknown")
        result = await service.evaluate(
            _build_request(contact=contact), AsyncMock()
        )
        assert result.allowed is False
        assert result.reason == "missing_sms_consent"
        assert result.details["sms_consent_status"] == "unknown"

    async def test_missing_sms_consent_skipped_when_not_required(
        self, service: OutboundComplianceService, db_no_duplicate: AsyncMock
    ) -> None:
        """``require_sms_consent=False`` lets us bypass the consent gate."""
        contact = _StubContact(sms_consent_status=None)
        result = await service.evaluate(
            _build_request(contact=contact, require_sms_consent=False),
            db_no_duplicate,
        )
        assert result.allowed is True

    async def test_quiet_hours_blocks_inside_window(
        self, service: OutboundComplianceService
    ) -> None:
        campaign = _StubCampaign(
            quiet_hours_start=time(22, 0),
            quiet_hours_end=time(8, 0),
            quiet_hours_timezone="UTC",
        )
        # 03:00 UTC sits inside the 22:00–08:00 quiet window.
        result = await service.evaluate(
            _build_request(
                campaign=campaign,
                now=datetime(2026, 5, 21, 3, 0, tzinfo=UTC),
            ),
            AsyncMock(),
        )
        assert result.allowed is False
        assert result.reason == "quiet_hours"
        assert result.details["timezone"] == "UTC"

    async def test_quiet_hours_blocks_inside_daytime_window(
        self, service: OutboundComplianceService
    ) -> None:
        """``start <= end`` branch (no wraparound)."""
        campaign = _StubCampaign(
            quiet_hours_start=time(9, 0),
            quiet_hours_end=time(17, 0),
            quiet_hours_timezone="UTC",
        )
        result = await service.evaluate(
            _build_request(
                campaign=campaign,
                now=datetime(2026, 5, 21, 12, 0, tzinfo=UTC),
            ),
            AsyncMock(),
        )
        assert result.allowed is False
        assert result.reason == "quiet_hours"

    async def test_quiet_hours_allowed_outside_window(
        self,
        service: OutboundComplianceService,
        db_no_duplicate: AsyncMock,
    ) -> None:
        campaign = _StubCampaign(
            quiet_hours_start=time(22, 0),
            quiet_hours_end=time(8, 0),
            quiet_hours_timezone="UTC",
        )
        result = await service.evaluate(
            _build_request(
                campaign=campaign,
                now=datetime(2026, 5, 21, 15, 0, tzinfo=UTC),
            ),
            db_no_duplicate,
        )
        assert result.allowed is True

    async def test_quiet_hours_invalid_timezone_falls_back_to_utc(
        self,
        service: OutboundComplianceService,
    ) -> None:
        campaign = _StubCampaign(
            quiet_hours_start=time(22, 0),
            quiet_hours_end=time(8, 0),
            quiet_hours_timezone="Not/A_Real_Zone",
        )
        result = await service.evaluate(
            _build_request(
                campaign=campaign,
                now=datetime(2026, 5, 21, 3, 0, tzinfo=UTC),
            ),
            AsyncMock(),
        )
        # Falls back to UTC and still blocks because 03:00 UTC is inside the
        # window.
        assert result.allowed is False
        assert result.reason == "quiet_hours"
        assert result.details["timezone"] == "UTC"

    async def test_campaign_cap_blocks(
        self, service: OutboundComplianceService
    ) -> None:
        campaign = _StubCampaign(max_messages_per_campaign=10, messages_sent=10)
        result = await service.evaluate(
            _build_request(campaign=campaign), AsyncMock()
        )
        assert result.allowed is False
        assert result.reason == "campaign_send_cap_reached"
        assert result.details["max_messages_per_campaign"] == 10

    async def test_contact_cap_blocks(
        self, service: OutboundComplianceService
    ) -> None:
        campaign = _StubCampaign(max_messages_per_contact=3)
        campaign_contact = _StubCampaignContact(messages_sent=3)
        result = await service.evaluate(
            _build_request(
                campaign=campaign,
                campaign_contact=campaign_contact,
            ),
            AsyncMock(),
        )
        assert result.allowed is False
        assert result.reason == "contact_send_cap_reached"

    async def test_duplicate_initial_sms_blocks(
        self,
        service: OutboundComplianceService,
        db_with_duplicate: AsyncMock,
    ) -> None:
        campaign_contact = _StubCampaignContact(messages_sent=0)
        result = await service.evaluate(
            _build_request(campaign_contact=campaign_contact),
            db_with_duplicate,
        )
        assert result.allowed is False
        assert result.reason == "duplicate_campaign_contact"

    async def test_duplicate_check_skipped_for_non_initial_action(
        self,
        service: OutboundComplianceService,
        db_with_duplicate: AsyncMock,
    ) -> None:
        """Only ``campaign_initial_sms`` triggers the duplicate guard."""
        campaign_contact = _StubCampaignContact(messages_sent=0)
        result = await service.evaluate(
            _build_request(
                campaign_contact=campaign_contact,
                action_type="campaign_followup_sms",
            ),
            db_with_duplicate,
        )
        # Duplicate query would have returned True if invoked; allowed=True
        # proves we never called it.
        assert result.allowed is True
        db_with_duplicate.execute.assert_not_called()

    async def test_allowed_when_all_gates_pass(
        self,
        service: OutboundComplianceService,
        db_no_duplicate: AsyncMock,
    ) -> None:
        campaign_contact = _StubCampaignContact(messages_sent=0)
        result = await service.evaluate(
            _build_request(campaign_contact=campaign_contact),
            db_no_duplicate,
        )
        assert result.allowed is True
        assert result.details["action_type"] == "campaign_initial_sms"


# --------------------------------------------------------------------------- #
# apply_suppression() — persistence side-effects
# --------------------------------------------------------------------------- #


class TestApplySuppression:
    """``apply_suppression`` mirrors evaluate's verdict onto the join row."""

    def test_records_compliance_metadata_on_allowed(
        self, service: OutboundComplianceService
    ) -> None:
        campaign_contact = _StubCampaignContact()
        result = OutboundComplianceResult(allowed=True, details={"x": 1})
        now = datetime(2026, 5, 21, 12, 0, tzinfo=UTC)
        service.apply_suppression(campaign_contact, result, now=now)  # type: ignore[arg-type]
        assert campaign_contact.compliance_checked_at == now
        assert campaign_contact.last_compliance_result == {
            "allowed": True,
            "reason": None,
            "details": {"x": 1},
        }
        # Allowed → no suppression flags
        assert campaign_contact.suppressed_reason is None
        assert campaign_contact.status == CampaignContactStatus.PENDING

    def test_records_suppression_on_blocked(
        self, service: OutboundComplianceService
    ) -> None:
        campaign_contact = _StubCampaignContact()
        result = OutboundComplianceResult(allowed=False, reason="quiet_hours")
        service.apply_suppression(campaign_contact, result)  # type: ignore[arg-type]
        assert campaign_contact.suppressed_reason == "quiet_hours"
        assert campaign_contact.suppressed_at is not None
        # Non-opt-out reasons must NOT flip the status
        assert campaign_contact.status == CampaignContactStatus.PENDING
        assert campaign_contact.opted_out is False

    def test_marks_opted_out_when_reason_is_global_opt_out(
        self, service: OutboundComplianceService
    ) -> None:
        campaign_contact = _StubCampaignContact()
        result = OutboundComplianceResult(allowed=False, reason="global_opt_out")
        service.apply_suppression(campaign_contact, result)  # type: ignore[arg-type]
        assert campaign_contact.status == CampaignContactStatus.OPTED_OUT
        assert campaign_contact.opted_out is True
        assert campaign_contact.opted_out_at is not None


# --------------------------------------------------------------------------- #
# OutboundComplianceResult.as_dict — serialization
# --------------------------------------------------------------------------- #


class TestResultSerialization:
    def test_as_dict_omits_next_allowed_at_when_unset(self) -> None:
        result = OutboundComplianceResult(allowed=True, details={"x": 1})
        payload = result.as_dict()
        assert "next_allowed_at" not in payload
        assert payload == {"allowed": True, "reason": None, "details": {"x": 1}}

    def test_as_dict_includes_next_allowed_at_when_set(self) -> None:
        when = datetime(2026, 5, 21, 16, 0, tzinfo=UTC)
        result = OutboundComplianceResult(allowed=False, reason="quiet_hours", next_allowed_at=when)
        payload = result.as_dict()
        assert payload["next_allowed_at"] == when.isoformat()
