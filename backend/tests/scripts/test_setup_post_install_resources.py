"""Pin the customer-facing automation written by the post-install setup script.

The database accepts free-form JSON action config, so a missing consent flag,
transactional category, brand URL or guide link would not fail until a real job
completed and a customer received the wrong message. Keep that contract here.
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path
from typing import Any

import pytest

from app.schemas.automation import AUTOMATION_ACTION_TYPES, AUTOMATION_TRIGGER_TYPES

_SCRIPT = (
    Path(__file__).resolve().parents[3] / "scripts" / "ops" / "setup_post_install_resources.py"
)


@pytest.fixture(scope="module")
def script() -> Any:
    spec = importlib.util.spec_from_file_location("setup_post_install_resources", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _actions(script: Any) -> list[dict[str, Any]]:
    actions = script._build_actions(
        guide_url=script.DEFAULT_GUIDE_URL,
        sms_template=script.DEFAULT_SMS,
        email_subject=script.DEFAULT_EMAIL_SUBJECT,
        email_body=script.DEFAULT_EMAIL_BODY,
        with_sms=True,
        with_email=True,
        logger=logging.getLogger(__name__),
    )
    assert actions is not None
    return actions


def test_trigger_and_actions_are_dispatched_by_the_engine(script: Any) -> None:
    assert script.TRIGGER_TYPE in AUTOMATION_TRIGGER_TYPES
    assert {action["type"] for action in _actions(script)} <= set(AUTOMATION_ACTION_TYPES)


def test_sms_requires_consent_and_names_the_sender(script: Any) -> None:
    sms = next(action["config"] for action in _actions(script) if action["type"] == "send_sms")

    assert sms["require_consent"] is True
    assert "Maxteriors" in sms["message"]
    assert script.DEFAULT_GUIDE_URL in sms["message"]
    assert "{first_name}" in sms["message"]


def test_email_is_service_mail_with_explicit_workspace_brand(script: Any) -> None:
    config = next(action["config"] for action in _actions(script) if action["type"] == "send_email")

    assert config["transactional"] is True
    assert config["business_name"] == "Maxteriors"
    assert config["logo_url"] == (
        "https://go.maxteriorslighting.com/static/brand/maxteriors-logo.png"
    )
    assert script.DEFAULT_GUIDE_URL in config["message"]
    assert "offer" not in config["message"].lower()


def test_public_customer_urls_are_https_and_branded(script: Any) -> None:
    assert script.DEFAULT_GUIDE_URL.startswith("https://go.maxteriorslighting.com/")
    assert "/static/guides/index.html" in script.DEFAULT_GUIDE_URL
