"""Phone-number capability response tests."""

import uuid

from app.models.phone_number import PhoneNumber, PhoneNumberProvider
from app.schemas.phone_number import PhoneNumberResponse


def _response(*, provider: str, sms_enabled: bool, mms_enabled: bool) -> PhoneNumberResponse:
    return PhoneNumberResponse(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        phone_number="+12125550101",
        friendly_name=None,
        provider=provider,
        sms_enabled=sms_enabled,
        voice_enabled=True,
        mms_enabled=mms_enabled,
        imessage_enabled=False,
        mac_relay_sender_id=None,
        mac_relay_service="imessage",
        assigned_agent_id=None,
        lead_source_id=None,
        lead_source_campaign_id=None,
        tracking_label=None,
        lead_source=None,
        lead_source_campaign=None,
        is_active=True,
    )


def test_legacy_telnyx_sms_number_exposes_effective_mms_support() -> None:
    phone = PhoneNumber(
        provider=PhoneNumberProvider.TELNYX,
        sms_enabled=True,
        mms_enabled=False,
    )

    response = _response(provider="telnyx", sms_enabled=True, mms_enabled=False)

    assert phone.supports_mms is True
    assert response.mms_enabled is True


def test_non_telnyx_number_does_not_gain_mms_support() -> None:
    response = _response(provider="mac_relay", sms_enabled=True, mms_enabled=False)

    assert response.mms_enabled is False
