"""The automation config ``scripts/ops/setup_lead_automation.py`` writes.

That script is how the permholidaylights instant-quote funnel gets its rule:
every brand-new lead is tagged (what the operator filters on) and the lead
source is stamped with the Facebook Ads channel (what the ROI dashboard counts).
Nothing in the app validates that config at write time — a typo'd tag or an
invalid ``source_type`` only shows up as leads landing untagged or in the wrong
channel days later, so the shape is pinned here.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

from app.models.lead_source import LeadSourceType
from app.schemas.automation import AUTOMATION_ACTION_TYPES, AUTOMATION_TRIGGER_TYPES

# backend/tests/scripts/<this file> -> scripts/ops/setup_lead_automation.py
_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "ops" / "setup_lead_automation.py"


@pytest.fixture(scope="module")
def script() -> Any:
    """Import the ops script by path (it lives outside the ``app`` package)."""
    spec = importlib.util.spec_from_file_location("setup_lead_automation", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_defaults_match_the_permholidaylights_funnel(script: Any) -> None:
    """The funnel's selector and labels are the whole point of the script."""
    assert script.DEFAULT_SOURCE_DETAIL == "permholidaylights instant quote"
    assert script.DEFAULT_TAGS == ("Perm Light Lead", "Facebook")


def test_default_channel_is_a_real_lead_source_type(script: Any) -> None:
    """``--source-type`` is free-form text; an unknown value must not be the default.

    The channel is written straight onto ``lead_sources.source_type`` (a plain
    VARCHAR, no DB constraint), so a stale default here would silently break the
    ROI rollup rather than fail.
    """
    assert LeadSourceType(script.DEFAULT_SOURCE_TYPE) is LeadSourceType.FACEBOOK_ADS
    assert script.KEEP_SOURCE_TYPE not in {member.value for member in LeadSourceType}


def test_trigger_and_action_types_are_ones_the_engine_dispatches(script: Any) -> None:
    """A config the worker ignores would look installed but do nothing."""
    assert script.TRIGGER_TYPE in AUTOMATION_TRIGGER_TYPES
    actions = script._build_actions(list(script.DEFAULT_TAGS), "hi {first_name}", with_sms=True)
    assert {action["type"] for action in actions} <= set(AUTOMATION_ACTION_TYPES)


def test_tags_are_applied_before_the_text(script: Any) -> None:
    """Order matters: an unsendable phone must still leave the lead classified."""
    actions = script._build_actions(
        ["Perm Light Lead", "Facebook"], "hi {first_name}", with_sms=True
    )

    assert [action["type"] for action in actions] == ["add_tag", "add_tag", "send_sms"]
    assert [action["config"]["tag"] for action in actions[:2]] == [
        "Perm Light Lead",
        "Facebook",
    ]
    assert actions[-1]["config"] == {
        "message": "hi {first_name}",
        "fallbacks": {"first_name": "there"},
    }


def test_tag_only_automation_omits_the_sms_action(script: Any) -> None:
    """Tag-only is a supported shape, not a degenerate one."""
    actions = script._build_actions(["Perm Light Lead"], "hi", with_sms=False)
    assert [action["type"] for action in actions] == ["add_tag"]


@pytest.mark.parametrize(
    ("mode", "source_action", "expected"),
    [
        ("auto", "auto_text", False),
        ("auto", "auto_call", False),
        ("auto", "collect", True),
        ("auto", "enroll_campaign", True),
        ("on", "auto_text", True),
        ("off", "collect", False),
    ],
    ids=[
        "auto-skips-when-source-texts",
        "auto-skips-when-source-calls",
        "auto-sends-for-collect",
        "auto-sends-for-enroll",
        "on-forces-double-touch",
        "off-always-suppresses",
    ],
)
def test_sms_is_suppressed_when_the_lead_source_already_messages(
    script: Any, mode: str, source_action: str, expected: bool
) -> None:
    """The real prod failure this guards: two texts to one customer.

    A lead source set to ``auto_text`` already texts on capture
    (``lead_form._action_auto_text``). Adding ``send_sms`` to the automation on
    top of that sends a second message to every new lead — invisible in code
    review, obvious to the customer.
    """
    with_sms, reason = script._resolve_sms(mode, source_action)

    assert with_sms is expected
    assert reason, "the decision must be explained in the log line"


def test_sms_modes_are_the_documented_ones(script: Any) -> None:
    """``--sms`` is a choices= flag; the constants and the tuple must agree."""
    assert set(script.SMS_MODES) == {script.SMS_AUTO, script.SMS_ON, script.SMS_OFF}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ([" Perm Light Lead ", "Facebook"], ["Perm Light Lead", "Facebook"]),
        (["Facebook", "facebook"], ["Facebook"]),
        (["Perm Light Lead", "", "   "], ["Perm Light Lead"]),
    ],
    ids=["trims", "dedupes-case-insensitively", "drops-blanks"],
)
def test_normalize_tags(script: Any, raw: list[str], expected: list[str]) -> None:
    """Repeated ``--tag`` flags are operator input; duplicates are not new tags."""
    assert script._normalize_tags(raw) == expected
