"""Selector semantics for post-install ``job_completed`` automations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services.automations.events import EVENT_JOB_COMPLETED, event_matches_trigger_config


def _days_ago(days: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


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


def test_recent_job_fires() -> None:
    assert (
        event_matches_trigger_config(EVENT_JOB_COMPLETED, {}, {"scheduled_start": _days_ago(3)})
        is True
    )


def test_long_overdue_job_does_not_text_the_customer() -> None:
    """A two-year-old imported job marked complete must not ask 'how did we do?'."""
    assert (
        event_matches_trigger_config(EVENT_JOB_COMPLETED, {}, {"scheduled_start": _days_ago(730)})
        is False
    )


def test_age_window_is_configurable_and_disablable() -> None:
    stale = {"scheduled_start": _days_ago(90)}

    assert event_matches_trigger_config(EVENT_JOB_COMPLETED, {"max_job_age_days": 120}, stale)
    assert event_matches_trigger_config(EVENT_JOB_COMPLETED, {"max_job_age_days": 0}, stale)
    assert event_matches_trigger_config(EVENT_JOB_COMPLETED, {"max_job_age_days": None}, stale)
    assert not event_matches_trigger_config(EVENT_JOB_COMPLETED, {"max_job_age_days": 30}, stale)


def test_unknown_or_unparseable_date_never_mutes_a_real_workflow() -> None:
    for payload in ({}, {"scheduled_start": None}, {"scheduled_start": "last tuesday"}):
        assert event_matches_trigger_config(EVENT_JOB_COMPLETED, {}, payload) is True


def test_naive_timestamp_is_treated_as_utc_not_crashed_on() -> None:
    naive = (datetime.now(UTC) - timedelta(days=400)).replace(tzinfo=None).isoformat()

    payload = {"scheduled_start": naive}

    assert event_matches_trigger_config(EVENT_JOB_COMPLETED, {}, payload) is False


def test_stale_job_is_dropped_even_when_it_is_a_lighting_project() -> None:
    """The age guard is always on — a selector match must not bypass it."""
    assert (
        event_matches_trigger_config(
            EVENT_JOB_COMPLETED,
            {"lighting_project_only": True},
            {
                "lighting_project_id": "8db993c0-d92a-489a-a8c4-e2359f0e9c0e",
                "scheduled_start": _days_ago(365),
            },
        )
        is False
    )
