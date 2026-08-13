"""Provisioning contract for the canonical lead-to-call acquisition funnel."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.models.lead_source import LeadSourceType
from app.schemas.automation import AUTOMATION_ACTION_TYPES, AUTOMATION_TRIGGER_TYPES

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "ops" / "setup_lead_automation.py"


@pytest.fixture(scope="module")
def script() -> Any:
    spec = importlib.util.spec_from_file_location("setup_lead_automation", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_defaults_match_the_permholidaylights_funnel(script: Any) -> None:
    assert script.DEFAULT_SOURCE_DETAIL == "permholidaylights instant quote"
    assert script.DEFAULT_TAGS == ("Perm Light Lead", "Facebook")
    assert LeadSourceType(script.DEFAULT_SOURCE_TYPE) is LeadSourceType.FACEBOOK_ADS


def test_workflow_is_bounded_consent_gated_and_hands_off_to_ai(script: Any) -> None:
    actions = script._build_actions(
        list(script.DEFAULT_TAGS),
        "hi {first_name}",
        with_sms=True,
        agent_id="11111111-1111-1111-1111-111111111111",
    )

    assert {action["type"] for action in actions} <= set(AUTOMATION_ACTION_TYPES)
    assert [action["type"] for action in actions[:2]] == ["add_tag", "add_tag"]
    assert [action["type"] for action in actions[2:]] == [
        "branch",
        "send_sms",
        "wait",
        "branch",
        "send_sms",
        "wait",
        "branch",
        "send_sms",
    ]
    sends = [action for action in actions if action["type"] == "send_sms"]
    assert len(sends) == 3
    assert all(action["config"]["require_consent"] is True for action in sends)
    assert all(
        action["config"]["quiet_hours_start"] == "21:00"
        and action["config"]["quiet_hours_end"] == "08:00"
        for action in sends
    )
    assert all(
        action["config"]["agent_id"] == "11111111-1111-1111-1111-111111111111" for action in sends
    )
    branches = [action for action in actions if action["type"] == "branch"]
    assert all(action["config"]["then_goto"] == "__end__" for action in branches)
    assert all(
        {rule["field"] for rule in action["config"]["conditions"]}
        == {"last_appointment_status", "sms_consent_status", "status"}
        for action in branches
    )
    consent_rules = [
        rule
        for branch in branches
        for rule in branch["config"]["conditions"]
        if rule["field"] == "sms_consent_status"
    ]
    assert all(
        rule["operator"] == "not_equals" and rule["value"] == "opted_in" for rule in consent_rules
    )


def test_trigger_is_source_scoped_and_names_the_acquisition_funnel(script: Any) -> None:
    config = script._build_trigger_config("ls_test", "source-id", "quote form")

    assert script.TRIGGER_TYPE in AUTOMATION_TRIGGER_TYPES
    assert config == {
        "lead_source_public_key": "ls_test",
        "lead_source_id": "source-id",
        "source_detail": "quote form",
        "funnel_id": "acquisition:lead-source:source-id",
    }


def test_source_is_deliberately_moved_to_collect_to_prevent_double_send(script: Any) -> None:
    with_sms, reason = script._resolve_sms(script.SMS_AUTO, "auto_text")

    assert with_sms is True
    assert "changed" in reason


def test_tag_only_mode_remains_supported(script: Any) -> None:
    actions = script._build_actions(["Perm Light Lead"], "hi", with_sms=False)
    assert actions == [{"type": "add_tag", "config": {"tag": "Perm Light Lead"}}]


def test_readiness_reports_every_funnel_prerequisite(script: Any) -> None:
    source = SimpleNamespace(enabled=False)
    agent = SimpleNamespace(
        is_active=True,
        enabled_tools=[],
        tool_settings={
            "website_lead_qualification_enabled": False,
            "qualification_questions": [],
        },
    )
    staff = SimpleNamespace(is_active=True, user_id=None)
    profile = SimpleNamespace(action_policies={"book_appointment": "ask"}, default_policy="ask")

    blockers = script._readiness_blockers(
        source=source,
        agent=agent,
        staff=staff,
        human_profile=profile,
        has_google_connection=False,
        auto_pipeline_enabled=False,
        stage_names={"Qualified"},
        consent_integration_confirmed=False,
    )

    assert any("disabled" in blocker for blocker in blockers)
    assert any("missing tools" in blocker for blocker in blockers)
    assert any("qualification" in blocker for blocker in blockers)
    assert any("must be auto" in blocker for blocker in blockers)
    assert any("bookable staff" in blocker for blocker in blockers)
    assert any("Google Calendar" in blocker for blocker in blockers)
    assert any("auto-pipeline" in blocker for blocker in blockers)
    assert any("Visit/Demo Scheduled" in blocker for blocker in blockers)
    assert any("sms_consent" in blocker for blocker in blockers)


def test_ready_configuration_has_no_blockers(script: Any) -> None:
    source = SimpleNamespace(enabled=True)
    agent = SimpleNamespace(
        is_active=True,
        enabled_tools=["book_appointment"],
        tool_settings={
            "website_lead_qualification_enabled": True,
            "qualification_questions": ["What project do you need?"],
            "qualification_min_score": 60,
            "qualification_booking_label": "consultation call",
        },
    )
    staff = SimpleNamespace(is_active=True, user_id=7)
    profile = SimpleNamespace(action_policies={"book_appointment": "auto"}, default_policy="ask")

    assert (
        script._readiness_blockers(
            source=source,
            agent=agent,
            staff=staff,
            human_profile=profile,
            has_google_connection=True,
            auto_pipeline_enabled=True,
            stage_names={"Qualified", "Visit/Demo Scheduled"},
            consent_integration_confirmed=True,
        )
        == []
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ([" Perm Light Lead ", "Facebook"], ["Perm Light Lead", "Facebook"]),
        (["Facebook", "facebook"], ["Facebook"]),
        (["Perm Light Lead", "", "   "], ["Perm Light Lead"]),
    ],
)
def test_normalize_tags(script: Any, raw: list[str], expected: list[str]) -> None:
    assert script._normalize_tags(raw) == expected
