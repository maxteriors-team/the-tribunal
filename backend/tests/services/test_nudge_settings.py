"""Tests for defensive workspace nudge-settings parsing."""

import pytest

from app.services.nudges.nudge_settings import get_nudge_settings


@pytest.mark.parametrize("workspace_settings", [None, [], "invalid", 1])
def test_non_mapping_workspace_settings_use_defaults(workspace_settings: object) -> None:
    assert get_nudge_settings(workspace_settings) == {}


def test_missing_or_malformed_nested_settings_use_defaults() -> None:
    assert get_nudge_settings({}) == {}
    assert get_nudge_settings({"nudge_settings": None}) == {}
    assert get_nudge_settings({"nudge_settings": []}) == {}


def test_valid_nudge_settings_are_returned() -> None:
    settings = {"enabled": False, "delivery_channels": ["push"]}

    assert get_nudge_settings({"nudge_settings": settings}) == settings
