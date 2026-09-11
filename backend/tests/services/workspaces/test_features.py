"""Workspace feature gates fail closed against untrusted settings JSON."""

from app.services.workspaces.features import TREE_LIGHT_QUOTER, workspace_feature_enabled


def test_workspace_feature_requires_exact_true() -> None:
    assert workspace_feature_enabled({"features": {TREE_LIGHT_QUOTER: True}}, TREE_LIGHT_QUOTER)

    for settings in (
        None,
        {},
        {"features": None},
        {"features": []},
        {"features": {TREE_LIGHT_QUOTER: False}},
        {"features": {TREE_LIGHT_QUOTER: 1}},
        {"features": {TREE_LIGHT_QUOTER: "true"}},
    ):
        assert not workspace_feature_enabled(settings, TREE_LIGHT_QUOTER)
