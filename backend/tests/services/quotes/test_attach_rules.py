"""Unit tests for the attach-rule config reader and evaluator.

Pure and DB-free: :func:`get_attach_rules_config` only needs an object with
``id`` and ``settings``, and :func:`evaluate_attach_rules` takes a config plus
two plain iterables, so every rule mode is exercised without Postgres.

The load-bearing case here is the corrupt blob. This config is read on the quote
save path, so a hand-edited or half-migrated ``workspace.settings`` must degrade
to advisory defaults rather than 500 a rep mid-sale.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.schemas.attach_rules import DEFAULT_PROMPT_TEMPLATE, AttachRule, AttachRulesSettings
from app.services.quotes.attach_rules import (
    evaluate_attach_rules,
    find_rule,
    render_prompt,
)
from app.services.quotes.attach_rules_config import SETTINGS_KEY, get_attach_rules_config


class FakeWorkspace:
    """Minimal stand-in for a ``Workspace`` (id + settings blob)."""

    def __init__(self, settings: Any) -> None:
        self.id = uuid.uuid4()
        self.settings = settings


def _config(**overrides: Any) -> AttachRulesSettings:
    """An enabled config with one roof rule, overridable per test."""
    base: dict[str, Any] = {
        "enabled": True,
        "rules": [
            AttachRule(
                primary_category="roof",
                suggested_categories=["gutters", "trim"],
                mode="advisory",
            )
        ],
    }
    base.update(overrides)
    return AttachRulesSettings(**base)


# --------------------------------------------------------------------------- #
# Config reading (lenient)
# --------------------------------------------------------------------------- #
def test_unset_settings_yield_advisory_defaults() -> None:
    """A workspace that never configured anything still gets the prompt."""
    config = get_attach_rules_config(FakeWorkspace({}))

    assert config.enabled is True
    assert config.rules
    assert {rule.mode for rule in config.rules} == {"advisory"}


def test_shipped_defaults_are_never_blocking() -> None:
    """Ship soft: the operator watches attach rate first, then tightens."""
    assert all(rule.mode != "blocking" for rule in AttachRulesSettings().rules)


def test_null_settings_column_yields_defaults() -> None:
    """``settings`` is nullable in older rows; NULL must read as empty."""
    assert get_attach_rules_config(FakeWorkspace(None)).enabled is True


def test_corrupt_blob_falls_back_to_defaults() -> None:
    """A hand-edited blob returns defaults instead of erroring.

    ``rules`` is a string where a list belongs and ``enabled`` is a dict, so
    validation cannot possibly succeed. The read must still hand back a usable
    config: this runs on the quote save path, and a broken settings row must not
    stand between a rep and a sold job.
    """
    workspace = FakeWorkspace({SETTINGS_KEY: {"rules": "not-a-list", "enabled": {"nope": True}}})

    config = get_attach_rules_config(workspace)

    assert config == AttachRulesSettings()
    assert config.enabled is True


def test_non_dict_blob_falls_back_to_defaults() -> None:
    """The key holding a scalar (a bad merge) reads as unset, not as a crash."""
    assert get_attach_rules_config(FakeWorkspace({SETTINGS_KEY: "off"})) == AttachRulesSettings()


def test_partial_blob_keeps_defaults_for_absent_keys() -> None:
    """A blob that only sets one key must not blank the rest of the config."""
    workspace = FakeWorkspace({SETTINGS_KEY: {"require_dismissal_reason": False}})

    config = get_attach_rules_config(workspace)

    assert config.require_dismissal_reason is False
    assert config.rules == AttachRulesSettings().rules


def test_unknown_keys_are_ignored() -> None:
    """Forward-compat: a key written by a newer build must not fail the read."""
    workspace = FakeWorkspace({SETTINGS_KEY: {"enabled": False, "future_knob": 7}})

    assert get_attach_rules_config(workspace).enabled is False


def test_blank_and_duplicate_categories_are_cleaned() -> None:
    """Sloppy operator input is cleaned, not rejected."""
    workspace = FakeWorkspace(
        {
            SETTINGS_KEY: {
                "rules": [
                    {
                        "primary_category": " roof ",
                        "suggested_categories": ["Gutters", "", "  ", "gutters"],
                    }
                ]
            }
        }
    )

    rule = get_attach_rules_config(workspace).rules[0]

    assert rule.primary_category == "roof"
    assert rule.suggested_categories == ["Gutters"]


# --------------------------------------------------------------------------- #
# Prompt rendering (never raises)
# --------------------------------------------------------------------------- #
def test_prompt_interpolates_the_primary_service() -> None:
    assert render_prompt("Attach something to this {primary} job.", "roof") == (
        "Attach something to this roof job."
    )


def test_prompt_with_unknown_placeholder_falls_back() -> None:
    """A typo'd placeholder must not break every save in the workspace."""
    assert render_prompt("Ask about {gutters}", "roof") == DEFAULT_PROMPT_TEMPLATE.format(
        primary="roof"
    )


def test_prompt_with_unclosed_brace_falls_back() -> None:
    assert render_prompt("Ask about {primary", "roof") == DEFAULT_PROMPT_TEMPLATE.format(
        primary="roof"
    )


def test_prompt_without_placeholder_renders_verbatim() -> None:
    assert render_prompt("Always ask about add-ons.", "roof") == "Always ask about add-ons."


# --------------------------------------------------------------------------- #
# Rule lookup
# --------------------------------------------------------------------------- #
def test_rule_lookup_is_case_and_whitespace_insensitive() -> None:
    """``service_category`` is free-form text; a capital G must still match."""
    config = _config()

    assert find_rule(config, "  ROOF ") is not None


def test_rule_lookup_misses_return_none() -> None:
    assert find_rule(_config(), "windows") is None
    assert find_rule(_config(), None) is None
    assert find_rule(_config(), "   ") is None


def test_first_matching_rule_wins() -> None:
    """Duplicates are an editing mistake; the visible top rule is the truth."""
    config = AttachRulesSettings(
        rules=[
            AttachRule(primary_category="roof", suggested_categories=["gutters"]),
            AttachRule(primary_category="roof", suggested_categories=["trim"], mode="blocking"),
        ]
    )

    rule = find_rule(config, "roof")

    assert rule is not None
    assert rule.suggested_categories == ["gutters"]


# --------------------------------------------------------------------------- #
# Evaluation — when to stay quiet
# --------------------------------------------------------------------------- #
def test_missing_attach_returns_a_warning() -> None:
    """The whole point: a roof job with nothing attached gets prompted."""
    warning = evaluate_attach_rules(_config(), primary_service="roof", present_categories=["roof"])

    assert warning is not None
    assert warning.mode == "advisory"
    assert warning.suggested_categories == ["gutters", "trim"]
    assert "roof" in warning.message


def test_present_attach_is_silent() -> None:
    """Any one suggestion satisfies the rule — it is any-of, not all-of."""
    assert (
        evaluate_attach_rules(
            _config(), primary_service="roof", present_categories=["roof", "gutters"]
        )
        is None
    )


def test_present_attach_matches_case_insensitively() -> None:
    """A price book that spells it "Gutters" still satisfies a "gutters" rule."""
    assert (
        evaluate_attach_rules(
            _config(), primary_service="roof", present_categories=["roof", " Gutters "]
        )
        is None
    )


def test_disabled_config_is_silent() -> None:
    assert (
        evaluate_attach_rules(
            _config(enabled=False), primary_service="roof", present_categories=["roof"]
        )
        is None
    )


def test_off_mode_is_silent() -> None:
    """A muted rule keeps its categories for later but says nothing now."""
    config = AttachRulesSettings(
        rules=[AttachRule(primary_category="roof", suggested_categories=["gutters"], mode="off")]
    )

    assert (
        evaluate_attach_rules(config, primary_service="roof", present_categories=["roof"]) is None
    )


def test_uncategorized_quote_is_silent() -> None:
    """No primary service means no job type to reason about."""
    assert (
        evaluate_attach_rules(_config(), primary_service=None, present_categories=[None, None])
        is None
    )


def test_unmatched_primary_service_is_silent() -> None:
    assert (
        evaluate_attach_rules(_config(), primary_service="windows", present_categories=["windows"])
        is None
    )


def test_rule_with_no_suggestions_is_silent() -> None:
    config = AttachRulesSettings(
        rules=[AttachRule(primary_category="roof", suggested_categories=[])]
    )

    assert (
        evaluate_attach_rules(config, primary_service="roof", present_categories=["roof"]) is None
    )


def test_rule_suggesting_only_itself_is_silent() -> None:
    """A self-referential rule can never be satisfied, so it must not nag."""
    config = AttachRulesSettings(
        rules=[AttachRule(primary_category="roof", suggested_categories=["Roof"])]
    )

    assert (
        evaluate_attach_rules(config, primary_service="roof", present_categories=["roof"]) is None
    )


# --------------------------------------------------------------------------- #
# Evaluation — warning payload
# --------------------------------------------------------------------------- #
def test_blocking_mode_is_reported_on_the_warning() -> None:
    config = AttachRulesSettings(
        rules=[
            AttachRule(primary_category="siding", suggested_categories=["trim"], mode="blocking")
        ]
    )

    warning = evaluate_attach_rules(config, primary_service="siding", present_categories=["siding"])

    assert warning is not None
    assert warning.mode == "blocking"


def test_warning_carries_the_dismissal_vocabulary() -> None:
    """The builder renders the dismissal UI without a second settings fetch."""
    config = _config(dismissal_reasons=["Customer declined"], require_dismissal_reason=False)

    warning = evaluate_attach_rules(config, primary_service="roof", present_categories=["roof"])

    assert warning is not None
    assert warning.dismissal_reasons == ["Customer declined"]
    assert warning.require_dismissal_reason is False


def test_warning_labels_the_primary_as_the_operator_spelled_it() -> None:
    """The rule's spelling wins over however the price book capitalized it."""
    config = AttachRulesSettings(
        rules=[AttachRule(primary_category="Roof Replacement", suggested_categories=["gutters"])]
    )

    warning = evaluate_attach_rules(
        config, primary_service="roof replacement", present_categories=["roof replacement"]
    )

    assert warning is not None
    assert warning.primary_service == "Roof Replacement"
