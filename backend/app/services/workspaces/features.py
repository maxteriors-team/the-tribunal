"""Fail-closed workspace feature gates stored in untrusted settings JSON."""

from collections.abc import Mapping
from typing import Final, Literal

WorkspaceFeature = Literal["tree_light_quoter"]
TREE_LIGHT_QUOTER: Final[WorkspaceFeature] = "tree_light_quoter"


def workspace_feature_enabled(settings: object, feature: WorkspaceFeature) -> bool:
    """Return true only for an explicitly enabled, well-shaped workspace feature."""
    if not isinstance(settings, Mapping):
        return False
    features = settings.get("features")
    return isinstance(features, Mapping) and features.get(feature) is True
