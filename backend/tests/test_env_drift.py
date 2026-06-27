"""Tests for committed environment-template drift checks."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECK_ENV_DRIFT_PATH = REPO_ROOT / "scripts" / "dev" / "check_env_drift.py"


def load_check_env_drift() -> ModuleType:
    """Load the root drift-check script as a testable module."""
    spec = importlib.util.spec_from_file_location("check_env_drift", CHECK_ENV_DRIFT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_env_templates_match_configured_and_used_variables() -> None:
    """The committed templates should stay in sync with backend/frontend env usage."""
    check_env_drift = load_check_env_drift()

    assert check_env_drift.main() == 0
