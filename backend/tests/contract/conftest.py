"""Pytest fixtures for webhook contract tests.

The signing/HTTP helpers live in ``_helpers.py`` so they can be imported
by name without colliding with pytest's auto-discovery of ``conftest``
modules. This file only exposes the per-test pytest fixtures.
"""

from __future__ import annotations

import pytest

from tests.contract._helpers import (
    ResendSigner,
    TelnyxSigner,
    new_resend_signer,
    new_telnyx_signer,
)


@pytest.fixture
def telnyx_signer() -> TelnyxSigner:
    """Fresh ed25519 keypair per test — keeps signing state isolated."""
    return new_telnyx_signer()


@pytest.fixture
def resend_signer() -> ResendSigner:
    """Fresh Svix ``whsec_<...>`` secret + stable ``msg_id`` per test."""
    return new_resend_signer()
