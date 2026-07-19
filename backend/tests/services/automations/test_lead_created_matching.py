"""Unit tests for ``lead_created_event_matches`` selector semantics.

The matcher decides whether a queued ``lead_created`` event should run a given
automation. Rules under test:

* no selectors configured -> matches every lead (workspace-wide);
* a configured selector matches on public key, lead-source id, or source_detail;
* ``source_detail`` matching is case-insensitive and whitespace-trimmed;
* selectors are permissive OR (any match wins), so the Facebook funnel is caught
  by its stable public key even when the landing page omits source_detail.
"""

from __future__ import annotations

import pytest

from app.services.automations.events import (
    AUTOMATION_EVENT_TRIGGERS,
    EVENT_LEAD_CREATED,
    lead_created_event_matches,
)

PUBLIC_KEY = "ls_n2dSPTZe"
SOURCE_ID = "11111111-1111-1111-1111-111111111111"
SOURCE_DETAIL = "permholidaylights instant quote"


def _payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "lead_source_id": SOURCE_ID,
        "lead_source_public_key": PUBLIC_KEY,
        "source_detail": SOURCE_DETAIL,
        "is_new_lead": True,
    }
    base.update(overrides)
    return base


def test_lead_created_is_registered_event_trigger() -> None:
    assert EVENT_LEAD_CREATED == "lead_created"
    assert EVENT_LEAD_CREATED in AUTOMATION_EVENT_TRIGGERS


def test_no_selectors_matches_any_lead() -> None:
    assert lead_created_event_matches({}, _payload()) is True
    assert lead_created_event_matches(None, _payload()) is True


def test_matches_by_public_key() -> None:
    config = {"lead_source_public_key": PUBLIC_KEY}
    assert lead_created_event_matches(config, _payload()) is True


def test_mismatch_by_public_key() -> None:
    config = {"lead_source_public_key": "ls_somethingelse"}
    assert lead_created_event_matches(config, _payload()) is False


def test_matches_by_lead_source_id() -> None:
    config = {"lead_source_id": SOURCE_ID}
    assert lead_created_event_matches(config, _payload(lead_source_public_key="ls_other")) is True


def test_matches_by_source_detail_case_insensitive() -> None:
    config = {"source_detail": "  PermHolidayLights Instant Quote  "}
    payload = _payload(
        lead_source_public_key="ls_other",
        lead_source_id="00000000-0000-0000-0000-000000000000",
    )
    assert lead_created_event_matches(config, payload) is True


def test_source_detail_mismatch() -> None:
    config = {"source_detail": SOURCE_DETAIL}
    payload = _payload(
        lead_source_public_key="ls_other",
        lead_source_id="00000000-0000-0000-0000-000000000000",
        source_detail="some other landing page",
    )
    assert lead_created_event_matches(config, payload) is False


def test_or_semantics_public_key_wins_when_source_detail_missing() -> None:
    """The funnel is caught by its key even when the page omits source_detail."""
    config = {"lead_source_public_key": PUBLIC_KEY, "source_detail": SOURCE_DETAIL}
    payload = _payload(source_detail=None)
    assert lead_created_event_matches(config, payload) is True


def test_null_payload_source_detail_does_not_crash() -> None:
    config = {"source_detail": SOURCE_DETAIL}
    assert lead_created_event_matches(config, {"source_detail": None}) is False


@pytest.mark.parametrize("blank", ["", "   ", None])
def test_blank_config_selectors_are_ignored(blank: object) -> None:
    """A selector present but blank must not narrow (falls back to match-any)."""
    config = {"lead_source_public_key": blank}
    assert lead_created_event_matches(config, _payload()) is True
