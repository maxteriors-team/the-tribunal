"""Unit tests for the unsold-quote follow-up config reader.

Pure and DB-free: :func:`get_unsold_quote_config` only needs an object with
``id`` and ``settings``.

Two properties carry weight here. The reader must never 500 a settings page on a
hand-edited blob — and unlike the attach rules, which fail *open* because an
advisory prompt is harmless, a config this reader cannot parse must fail
**closed**: the fallback is disabled, because the alternative is texting past
customers from a config nobody can read. The other is ordering: the worker walks
``touches`` in sequence, so a mis-ordered list would fire day 90 before day 30.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from pydantic import ValidationError

from app.schemas.unsold_quotes import (
    MAX_TOUCHES,
    UnsoldQuoteSettings,
    UnsoldQuoteSettingsUpdate,
    UnsoldQuoteTouch,
)
from app.services.quotes.unsold_quote_config import SETTINGS_KEY, get_unsold_quote_config


class FakeWorkspace:
    """Minimal stand-in for a ``Workspace`` (id + settings blob)."""

    def __init__(self, settings: Any) -> None:
        self.id = uuid.uuid4()
        self.settings = settings


# --------------------------------------------------------------------------- #
# Config reading
# --------------------------------------------------------------------------- #
def test_unset_settings_ship_the_sequence_switched_off() -> None:
    """Defaults describe a 30/60/90 sequence, but do not run it."""
    config = get_unsold_quote_config(FakeWorkspace({}))

    assert config.enabled is False
    assert config.day_offsets == [30, 60, 90]
    assert [touch.hook for touch in config.touches] == [
        "price_validity",
        "seasonal",
        "financing",
    ]
    assert config.value_threshold == 5000.0
    assert config.quiet_hours_start == "21:00"
    assert config.quiet_hours_end == "08:00"


def test_stored_config_round_trips() -> None:
    config = get_unsold_quote_config(
        FakeWorkspace(
            {
                SETTINGS_KEY: {
                    "enabled": True,
                    "value_threshold": 15000,
                    "touches": [
                        {"day_offset": 21, "hook": "seasonal", "template_name": "Spring"},
                        {"day_offset": 45, "hook": "financing"},
                    ],
                }
            }
        )
    )

    assert config.enabled is True
    assert config.day_offsets == [21, 45]
    assert config.touches[0].template_name == "Spring"
    assert config.value_threshold == 15000


def test_corrupt_blob_reads_as_disabled_defaults() -> None:
    """Fail closed: an unreadable config must not send anything."""
    config = get_unsold_quote_config(FakeWorkspace({SETTINGS_KEY: {"touches": "not-a-list"}}))

    assert config.enabled is False
    assert config.day_offsets == [30, 60, 90]


def test_non_dict_blob_is_ignored() -> None:
    assert get_unsold_quote_config(FakeWorkspace({SETTINGS_KEY: ["nope"]})).enabled is False
    assert get_unsold_quote_config(FakeWorkspace(None)).enabled is False


def test_unknown_keys_are_ignored_not_fatal() -> None:
    config = get_unsold_quote_config(
        FakeWorkspace({SETTINGS_KEY: {"enabled": True, "leftover_from_v1": 7}})
    )
    assert config.enabled is True


# --------------------------------------------------------------------------- #
# Cadence normalization
# --------------------------------------------------------------------------- #
def test_touches_are_sorted_and_de_duplicated() -> None:
    """Order is load-bearing: the worker walks this list in sequence."""
    config = UnsoldQuoteSettings(
        touches=[
            UnsoldQuoteTouch(day_offset=90, hook="financing"),
            UnsoldQuoteTouch(day_offset=30, hook="price_validity"),
            UnsoldQuoteTouch(day_offset=30, hook="seasonal"),
        ]
    )

    assert config.day_offsets == [30, 90]
    assert config.touches[0].hook == "price_validity"


def test_touch_list_is_capped() -> None:
    config = UnsoldQuoteSettings(
        touches=[UnsoldQuoteTouch(day_offset=offset) for offset in range(1, 20)],
        max_touches=MAX_TOUCHES,
    )
    assert len(config.touches) == MAX_TOUCHES


def test_max_touches_shortens_without_deleting_configured_copy() -> None:
    config = UnsoldQuoteSettings(
        touches=[
            UnsoldQuoteTouch(day_offset=30),
            UnsoldQuoteTouch(day_offset=60),
            UnsoldQuoteTouch(day_offset=90),
        ],
        max_touches=1,
    )

    assert len(config.touches) == 3
    assert [touch.day_offset for touch in config.active_touches()] == [30]


def test_zero_max_touches_disables_sending_without_losing_the_plan() -> None:
    config = UnsoldQuoteSettings(enabled=True, max_touches=0)
    assert config.active_touches() == []
    assert len(config.touches) == 3


def test_blank_template_names_mean_use_the_built_in_copy() -> None:
    touch = UnsoldQuoteTouch(day_offset=30, template_name="   ", high_value_template_name="  X ")
    assert touch.template_name is None
    assert touch.high_value_template_name == "X"


# --------------------------------------------------------------------------- #
# Write-edge validation
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("offset", [0, -1, 731])
def test_impossible_day_offsets_are_rejected(offset: int) -> None:
    with pytest.raises(ValidationError):
        UnsoldQuoteTouch(day_offset=offset)


def test_unknown_hook_is_rejected() -> None:
    with pytest.raises(ValidationError):
        UnsoldQuoteTouch(day_offset=30, hook="pester")  # type: ignore[arg-type]


def test_negative_value_threshold_is_rejected() -> None:
    with pytest.raises(ValidationError):
        UnsoldQuoteSettingsUpdate(value_threshold=-1)


@pytest.mark.parametrize("clock", ["25:00", "9pm", "08:75"])
def test_invalid_quiet_hours_are_rejected_at_the_write_edge(clock: str) -> None:
    with pytest.raises(ValidationError):
        UnsoldQuoteSettingsUpdate(quiet_hours_start=clock)


def test_blank_quiet_hours_clear_the_window() -> None:
    assert UnsoldQuoteSettingsUpdate(quiet_hours_start="  ").quiet_hours_start is None
