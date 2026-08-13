"""Selector semantics for post-install ``job_completed`` automations."""

from __future__ import annotations

from app.services.automations.events import EVENT_JOB_COMPLETED, event_matches_trigger_config


def test_job_completed_without_selector_matches_legacy_automations() -> None:
    """Adding a selector must not silently disable existing job workflows."""
    assert event_matches_trigger_config(EVENT_JOB_COMPLETED, {}, {}) is True
    assert event_matches_trigger_config(EVENT_JOB_COMPLETED, None, None) is True


def test_lighting_only_matches_structured_project_id() -> None:
    config = {"lighting_project_only": True}

    assert (
        event_matches_trigger_config(
            EVENT_JOB_COMPLETED,
            config,
            {"lighting_project_id": "8db993c0-d92a-489a-a8c4-e2359f0e9c0e"},
        )
        is True
    )


def test_lighting_only_rejects_service_job_without_project_id() -> None:
    config = {"lighting_project_only": True}

    assert (
        event_matches_trigger_config(
            EVENT_JOB_COMPLETED,
            config,
            {"title": "Landscape lighting repair", "lighting_project_id": None},
        )
        is False
    )


def test_lighting_only_never_guesses_from_customer_authored_title() -> None:
    """Words like 'install' are not a trustworthy type discriminator."""
    config = {"lighting_project_only": True}

    assert (
        event_matches_trigger_config(
            EVENT_JOB_COMPLETED,
            config,
            {"title": "Install outlet repair"},
        )
        is False
    )
