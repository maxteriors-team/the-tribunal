"""Which created deals count as a lead arriving on the board.

Regression cover for 2026-09-10: filing an already-quoted customer into
``Unqualified (archived)`` fired a "New Lead — Welcome Text" automation, so a
customer three proposals deep was texted "thanks for your interest".
"""

from __future__ import annotations

from app.services.automations.events import (
    EVENT_OPPORTUNITY_CREATED,
    event_matches_trigger_config,
)

NEW_LEAD = {"is_first_deal": True, "is_entry_stage": True}


def test_first_deal_in_entry_stage_is_a_new_lead() -> None:
    assert event_matches_trigger_config(EVENT_OPPORTUNITY_CREATED, {}, NEW_LEAD) is True


def test_second_deal_for_a_contact_already_on_the_board_does_not_match() -> None:
    payload = {"is_first_deal": False, "is_entry_stage": True}

    assert event_matches_trigger_config(EVENT_OPPORTUNITY_CREATED, {}, payload) is False


def test_card_filed_into_a_later_or_parked_stage_does_not_match() -> None:
    payload = {"is_first_deal": True, "is_entry_stage": False, "stage": "Unqualified (archived)"}

    assert event_matches_trigger_config(EVENT_OPPORTUNITY_CREATED, {}, payload) is False


def test_any_deal_opt_in_still_fires_for_filed_cards() -> None:
    """Owner-notification style automations can keep every-deal semantics."""
    payload = {"is_first_deal": False, "is_entry_stage": False}

    assert (
        event_matches_trigger_config(EVENT_OPPORTUNITY_CREATED, {"any_deal": True}, payload) is True
    )


def test_events_queued_before_the_flags_existed_keep_firing() -> None:
    """A pending event mid-deploy must not be silently dropped."""
    legacy = {"opportunity_id": "8db993c0-d92a-489a-a8c4-e2359f0e9c0e", "stage": "Qualified"}

    assert event_matches_trigger_config(EVENT_OPPORTUNITY_CREATED, {}, legacy) is True
    assert event_matches_trigger_config(EVENT_OPPORTUNITY_CREATED, None, None) is True
