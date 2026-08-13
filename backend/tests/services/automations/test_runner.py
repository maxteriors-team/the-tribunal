"""Cursor, goto and wait rules for multi-step workflows.

These are the rules that decide where a customer's workflow goes next, so they
are pinned here without a database. The fail-safe cases matter most: a dangling
goto must *end* the run rather than fall into the other branch's messages, and a
bad wait value must delay a send rather than release it early.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.services.automations.runner import (
    END_OF_WORKFLOW,
    GOTO_END,
    MAX_WAIT,
    branch_targets,
    normalize_steps,
    resolve_goto,
    step_at,
    wait_duration,
)


def _steps(*raw: dict) -> list:
    return normalize_steps(list(raw))


class TestNormalizeSteps:
    def test_assigns_positional_indexes(self):
        steps = _steps({"type": "send_sms"}, {"type": "wait"}, {"type": "send_email"})
        assert [s.index for s in steps] == [0, 1, 2]

    def test_legacy_steps_without_ids_are_preserved(self):
        """Automations authored before branching must keep running untouched."""
        steps = _steps({"type": "send_sms", "config": {"message": "hi"}})
        assert steps[0].step_id is None
        assert steps[0].config == {"message": "hi"}

    def test_type_is_lowercased(self):
        assert _steps({"type": "Send_SMS"})[0].type == "send_sms"

    def test_malformed_entries_are_dropped_not_raised(self):
        """One bad row must not take a workspace's automations offline."""
        steps = normalize_steps([{"type": "send_sms"}, "garbage", None, {"type": "wait"}])
        assert [s.type for s in steps] == ["send_sms", "wait"]
        assert [s.index for s in steps] == [0, 1]

    def test_non_list_actions_yield_no_steps(self):
        assert normalize_steps(None) == []
        assert normalize_steps({"type": "send_sms"}) == []

    def test_non_dict_config_falls_back_to_empty(self):
        assert _steps({"type": "wait", "config": "nope"})[0].config == {}

    def test_blank_ids_are_treated_as_absent(self):
        assert _steps({"type": "wait", "id": "   "})[0].step_id is None


class TestStepAt:
    def test_returns_step_in_range(self):
        steps = _steps({"type": "send_sms"}, {"type": "wait"})
        assert step_at(steps, 1).type == "wait"

    def test_cursor_past_end_finishes_run(self):
        """A persisted cursor can outlive an edit that shortened the workflow."""
        steps = _steps({"type": "send_sms"})
        assert step_at(steps, 5) is None

    def test_end_of_workflow_sentinel_is_not_a_step(self):
        steps = _steps({"type": "send_sms"})
        assert step_at(steps, END_OF_WORKFLOW) is None


class TestResolveGoto:
    def test_named_step_id_jumps_to_its_index(self):
        steps = _steps(
            {"type": "branch"},
            {"type": "send_sms"},
            {"type": "send_email", "id": "followup"},
        )
        assert resolve_goto(steps, "followup", fallthrough=1).index == 2

    def test_null_target_falls_through(self):
        steps = _steps({"type": "branch"}, {"type": "send_sms"})
        assert resolve_goto(steps, None, fallthrough=1).index == 1

    def test_end_sentinel_finishes_run(self):
        steps = _steps({"type": "branch"}, {"type": "send_sms"})
        assert resolve_goto(steps, GOTO_END, fallthrough=1).index == END_OF_WORKFLOW

    def test_dangling_target_ends_run_and_is_flagged(self):
        """A typo'd target must never fall into the other branch's messages."""
        steps = _steps({"type": "branch"}, {"type": "send_sms", "id": "real"})
        target = resolve_goto(steps, "typo", fallthrough=1)
        assert target.index == END_OF_WORKFLOW
        assert target.dangling is True

    def test_valid_target_is_not_flagged_dangling(self):
        steps = _steps({"type": "branch"}, {"type": "send_sms", "id": "real"})
        assert resolve_goto(steps, "real", fallthrough=1).dangling is False

    def test_backward_goto_is_allowed(self):
        """Cycles are legal; the step/resume budgets are what bound them."""
        steps = _steps({"type": "send_sms", "id": "top"}, {"type": "branch"})
        assert resolve_goto(steps, "top", fallthrough=2).index == 0


class TestBranchTargets:
    def test_defaults_to_fallthrough_on_both_sides(self):
        steps = _steps({"type": "branch"}, {"type": "send_sms"})
        when_true, when_false = branch_targets(steps, steps[0])
        assert when_true.index == 1
        assert when_false.index == 1

    def test_resolves_each_side_independently(self):
        steps = _steps(
            {"type": "branch", "config": {"then_goto": "won", "else_goto": GOTO_END}},
            {"type": "send_sms"},
            {"type": "send_email", "id": "won"},
        )
        when_true, when_false = branch_targets(steps, steps[0])
        assert when_true.index == 2
        assert when_false.index == END_OF_WORKFLOW


class TestWaitDuration:
    def test_missing_config_uses_legacy_one_hour_default(self):
        """Existing automations must keep the timing they already had."""
        assert wait_duration(None) == timedelta(hours=1)
        assert wait_duration({}) == timedelta(hours=1)

    @pytest.mark.parametrize(
        ("config", "expected"),
        [
            ({"minutes": 30}, timedelta(minutes=30)),
            ({"hours": 4}, timedelta(hours=4)),
            ({"days": 3}, timedelta(days=3)),
        ],
    )
    def test_each_unit(self, config, expected):
        assert wait_duration(config) == expected

    def test_units_sum(self):
        assert wait_duration({"days": 1, "hours": 12}) == timedelta(hours=36)

    def test_fractional_values_are_honoured(self):
        assert wait_duration({"hours": 1.5}) == timedelta(minutes=90)

    @pytest.mark.parametrize("bad", ["abc", None, True, [], {}])
    def test_unparseable_values_never_shorten_the_wait(self, bad):
        """A bad value must delay a send, never release it early."""
        assert wait_duration({"hours": bad}) == timedelta(hours=1)

    def test_negative_values_contribute_nothing(self):
        assert wait_duration({"hours": -5}) == timedelta(hours=1)

    def test_explicit_zero_means_no_wait(self):
        assert wait_duration({"hours": 0}) == timedelta()

    def test_string_numbers_are_accepted_from_jsonb(self):
        assert wait_duration({"hours": "2"}) == timedelta(hours=2)

    def test_absurd_value_is_capped(self):
        assert wait_duration({"days": 99999}) == MAX_WAIT
