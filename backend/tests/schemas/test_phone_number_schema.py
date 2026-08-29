"""Phone-number capability response tests."""

import uuid

import pytest
from pydantic import ValidationError

from app.models.phone_number import PhoneNumber, PhoneNumberProvider
from app.schemas.phone_number import InboundCallConfigRequest, PhoneNumberResponse


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


def test_existing_phone_responses_default_inbound_ai_to_off() -> None:
    response = _response(provider="telnyx", sms_enabled=True, mms_enabled=True)

    assert response.inbound_ai_enabled is False


def test_activation_can_reuse_existing_encrypted_destinations() -> None:
    request = InboundCallConfigRequest(enabled=True, assigned_agent_id=uuid.uuid4())

    assert request.fallback_number is None
    assert request.transfer_destination_number is None


@pytest.mark.parametrize("field", ["fallback_number", "transfer_destination_number"])
def test_inbound_destinations_are_stored_as_e164(field: str) -> None:
    request = InboundCallConfigRequest(
        enabled=False,
        **{field: "202-555-0123"},
    )

    assert getattr(request, field) == "+12025550123"


def test_activation_requires_an_explicit_agent() -> None:
    with pytest.raises(ValidationError):
        InboundCallConfigRequest(
            enabled=True,
            fallback_number="+12025550123",
            transfer_destination_number="+12025550124",
        )
