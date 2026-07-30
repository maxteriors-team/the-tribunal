"""Unit tests for the neighbour-messaging compliance gate and its config.

Pure — no database, so these run in default CI. This is the file that matters
legally: a radius search returns *addresses*, not permission, so every path that
could put a message in front of a stranger has to be closed here.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from pydantic import ValidationError

from app.models.neighbor_outreach import NeighborOutreachChannel, NeighborOutreachStatus
from app.schemas.neighbor_outreach import (
    NeighborOutreachSettings,
    NeighborOutreachSettingsUpdate,
)
from app.services.field_service.jobsite_radius import (
    DEFAULT_MAX_NEIGHBORS,
    DEFAULT_RADIUS_METERS,
    MAX_RADIUS_METERS,
    MIN_RADIUS_METERS,
)
from app.services.field_service.neighbor_outreach import (
    BLOCK_GLOBAL_OPT_OUT,
    BLOCK_MISSING_CONSENT,
    BLOCK_NO_CONTACT,
    BLOCK_NO_EMAIL_ADDRESS,
    BLOCK_NO_PHONE_NUMBER,
    CONSENT_OPTED_IN,
    messaging_block_reason,
)
from app.services.field_service.neighbor_outreach_config import (
    SETTINGS_KEY,
    get_neighbor_outreach_config,
)


class _FakeWorkspace:
    """Stand-in for a ``Workspace`` row: only ``id`` and ``settings`` are read."""

    def __init__(self, settings: Any) -> None:
        self.id = uuid.uuid4()
        self.settings = settings


def _reason(**overrides: Any) -> str | None:
    """A fully-consented SMS neighbour, with individual gates overridden per test."""
    kwargs: dict[str, Any] = {
        "channel": NeighborOutreachChannel.SMS,
        "has_contact": True,
        "phone_number": "+15551230000",
        "email": "neighbor@example.com",
        "consent_status": CONSENT_OPTED_IN,
        "compliance_reason": None,
    }
    kwargs.update(overrides)
    return messaging_block_reason(**kwargs)


# --------------------------------------------------------------------------- #
# The messaging gate
# --------------------------------------------------------------------------- #
class TestMessagingBlockReason:
    """Who may be messaged, and — mostly — who may not."""

    def test_fully_consented_contact_is_allowed(self) -> None:
        assert _reason() is None

    def test_print_needs_no_permission_at_all(self) -> None:
        """A door hanger is not a message: no contact, no consent, still fine."""
        assert (
            _reason(
                channel=NeighborOutreachChannel.PRINT,
                has_contact=False,
                phone_number=None,
                email=None,
                consent_status=None,
                compliance_reason=BLOCK_GLOBAL_OPT_OUT,
            )
            is None
        )

    # ----- the hard stop: no contact record ---------------------------- #
    def test_address_with_no_contact_record_is_never_messaged(self) -> None:
        """The core rule. A location harvested from a radius is not a lead you may text."""
        assert _reason(has_contact=False) == BLOCK_NO_CONTACT

    def test_no_contact_outranks_every_other_reason(self) -> None:
        """A stranger is refused for being a stranger, not for a missing phone."""
        assert (
            _reason(has_contact=False, phone_number=None, consent_status=None) == BLOCK_NO_CONTACT
        )

    @pytest.mark.parametrize(
        "channel", [NeighborOutreachChannel.SMS, NeighborOutreachChannel.EMAIL]
    )
    def test_no_contact_blocks_both_messaging_channels(
        self, channel: NeighborOutreachChannel
    ) -> None:
        assert _reason(channel=channel, has_contact=False) == BLOCK_NO_CONTACT

    # ----- opt-out ----------------------------------------------------- #
    def test_global_opt_out_is_respected(self) -> None:
        """The verdict from the shared compliance layer wins over local consent."""
        assert _reason(compliance_reason=BLOCK_GLOBAL_OPT_OUT) == BLOCK_GLOBAL_OPT_OUT

    def test_opt_out_beats_recorded_consent(self) -> None:
        """A contact who texted STOP is blocked even though consent is on record."""
        assert (
            _reason(consent_status=CONSENT_OPTED_IN, compliance_reason=BLOCK_GLOBAL_OPT_OUT)
            == BLOCK_GLOBAL_OPT_OUT
        )

    def test_opt_out_is_respected_on_the_email_channel_too(self) -> None:
        assert (
            _reason(channel=NeighborOutreachChannel.EMAIL, compliance_reason=BLOCK_GLOBAL_OPT_OUT)
            == BLOCK_GLOBAL_OPT_OUT
        )

    def test_any_compliance_reason_is_passed_through_verbatim(self) -> None:
        """No reason vocabulary of our own: the shared layer's string is the answer."""
        assert _reason(compliance_reason="quiet_hours") == "quiet_hours"

    # ----- consent ----------------------------------------------------- #
    @pytest.mark.parametrize("status", ["unknown", "opted_out", "pending", "", None])
    def test_anything_short_of_opted_in_blocks_sms(self, status: str | None) -> None:
        assert _reason(consent_status=status) == BLOCK_MISSING_CONSENT

    def test_consent_is_required_for_email_as_well(self) -> None:
        """This schema has one consent-of-record, so email inherits the same gate."""
        assert (
            _reason(channel=NeighborOutreachChannel.EMAIL, consent_status="unknown")
            == BLOCK_MISSING_CONSENT
        )

    # ----- nothing to send to ------------------------------------------ #
    def test_sms_needs_a_phone_number(self) -> None:
        assert _reason(phone_number=None) == BLOCK_NO_PHONE_NUMBER

    def test_email_needs_an_email_address(self) -> None:
        assert _reason(channel=NeighborOutreachChannel.EMAIL, email=None) == BLOCK_NO_EMAIL_ADDRESS

    def test_sms_does_not_require_an_email(self) -> None:
        assert _reason(email=None) is None

    def test_email_does_not_require_a_phone(self) -> None:
        assert _reason(channel=NeighborOutreachChannel.EMAIL, phone_number=None) is None


# --------------------------------------------------------------------------- #
# Workspace config
# --------------------------------------------------------------------------- #
class TestNeighborOutreachConfig:
    """A bad blob must fall back to the *safe* defaults, never 500 a read."""

    def test_defaults_are_off_and_print_only(self) -> None:
        config = get_neighbor_outreach_config(_FakeWorkspace({}))  # type: ignore[arg-type]
        assert config.enabled is False
        assert config.allow_messaging is False
        assert config.radius_meters == DEFAULT_RADIUS_METERS
        assert config.max_neighbors == DEFAULT_MAX_NEIGHBORS
        assert config.auto_generate_on_completion is True
        assert config.message_template_id is None

    def test_default_radius_is_about_a_block(self) -> None:
        """~150 m is the houses that watched the crew, not a mailing list."""
        assert DEFAULT_RADIUS_METERS == 150

    def test_stored_values_are_read_back(self) -> None:
        template_id = uuid.uuid4()
        workspace = _FakeWorkspace(
            {
                SETTINGS_KEY: {
                    "enabled": True,
                    "radius_meters": 300,
                    "max_neighbors": 12,
                    "auto_generate_on_completion": False,
                    "allow_messaging": True,
                    "message_template_id": str(template_id),
                }
            }
        )
        config = get_neighbor_outreach_config(workspace)  # type: ignore[arg-type]
        assert config.enabled is True
        assert config.radius_meters == 300
        assert config.max_neighbors == 12
        assert config.auto_generate_on_completion is False
        assert config.allow_messaging is True
        assert config.message_template_id == template_id

    def test_null_settings_column_falls_back_to_defaults(self) -> None:
        assert get_neighbor_outreach_config(_FakeWorkspace(None)).enabled is False  # type: ignore[arg-type]

    def test_non_dict_blob_falls_back_to_defaults(self) -> None:
        workspace = _FakeWorkspace({SETTINGS_KEY: "corrupt"})
        assert get_neighbor_outreach_config(workspace).enabled is False  # type: ignore[arg-type]

    def test_unparseable_blob_falls_back_to_safe_defaults(self) -> None:
        """A hand-edited radius of 9,999,999 must not enable a city-wide run."""
        workspace = _FakeWorkspace({SETTINGS_KEY: {"enabled": True, "radius_meters": 9_999_999}})
        config = get_neighbor_outreach_config(workspace)  # type: ignore[arg-type]
        assert config.enabled is False
        assert config.radius_meters == DEFAULT_RADIUS_METERS

    def test_partial_blob_keeps_defaults_for_absent_keys(self) -> None:
        workspace = _FakeWorkspace({SETTINGS_KEY: {"enabled": True}})
        config = get_neighbor_outreach_config(workspace)  # type: ignore[arg-type]
        assert config.enabled is True
        assert config.allow_messaging is False


class TestSettingsValidation:
    """Bounds are enforced at the edge so a bad value cannot be persisted."""

    def test_radius_below_the_floor_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            NeighborOutreachSettings(radius_meters=MIN_RADIUS_METERS - 1)

    def test_radius_above_the_ceiling_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            NeighborOutreachSettings(radius_meters=MAX_RADIUS_METERS + 1)

    def test_zero_neighbors_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            NeighborOutreachSettings(max_neighbors=0)

    def test_unknown_keys_are_rejected(self) -> None:
        """``extra=\"forbid\"`` catches a typo before it silently does nothing."""
        with pytest.raises(ValidationError):
            NeighborOutreachSettings(radius_metres=150)  # type: ignore[call-arg]

    def test_update_payload_is_fully_optional(self) -> None:
        update = NeighborOutreachSettingsUpdate()
        assert update.model_dump(exclude_unset=True) == {}

    def test_update_payload_enforces_the_same_bounds(self) -> None:
        with pytest.raises(ValidationError):
            NeighborOutreachSettingsUpdate(radius_meters=MAX_RADIUS_METERS + 1)


class TestEnumValues:
    """The persisted strings are part of the API contract and the DB column."""

    def test_status_values(self) -> None:
        assert [status.value for status in NeighborOutreachStatus] == [
            "pending",
            "contacted",
            "skipped",
            "converted",
        ]

    def test_channel_values_lead_with_print(self) -> None:
        assert [channel.value for channel in NeighborOutreachChannel] == [
            "print",
            "sms",
            "email",
        ]
