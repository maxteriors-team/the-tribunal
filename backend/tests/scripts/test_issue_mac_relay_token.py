"""Guards for the Mac relay token CLI.

Since audit H-4 the relay's bearer token *is* its tenancy decision, so this
script is the only supported way to provision or kill a relay host's
credential. It was silently dropped once during a squash merge — the webhook
kept rejecting forged tokens, but there was no longer any way to mint a real
one, and nothing failed to make that visible. These tests exist mostly so that
cannot happen quietly again.
"""

import argparse
import importlib.util
import sys
import uuid
from pathlib import Path

import pytest

from app.services.telephony.mac_relay_auth import (
    TOKEN_PREFIX,
    generate_mac_relay_token,
    hash_mac_relay_token,
)

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ops" / "issue_mac_relay_token.py"


def _load_script():
    """Import the ops script by path (it lives outside the app package)."""
    spec = importlib.util.spec_from_file_location("issue_mac_relay_token", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_script_is_present() -> None:
    """Without this file there is no way to provision a relay at all."""
    assert _SCRIPT.is_file(), (
        f"{_SCRIPT} is missing. H-4 makes the relay token the tenancy decision, "
        "so dropping this script leaves the relay unprovisionable."
    )


class TestOperatorSurface:
    """The flags an operator needs during an incident."""

    @pytest.fixture(scope="class")
    def parser(self) -> argparse.ArgumentParser:
        module = _load_script()
        parser = argparse.ArgumentParser()
        module._configure(parser)
        return parser

    def test_exposes_revoke(self, parser: argparse.ArgumentParser) -> None:
        """Revocation must not require minting a replacement.

        Rotation keeps the line working under a new credential; during an
        incident you want the opposite, without handing a fresh secret to a host
        you no longer trust.
        """
        assert "--revoke" in parser.format_help()

    def test_exposes_rotate(self, parser: argparse.ArgumentParser) -> None:
        assert "--rotate" in parser.format_help()

    def test_accepts_both_selectors(self, parser: argparse.ArgumentParser) -> None:
        help_text = parser.format_help()
        assert "--phone-number-id" in help_text
        assert "--number" in help_text

    def test_selectors_are_mutually_exclusive(self, parser: argparse.ArgumentParser) -> None:
        """Passing both would make the targeted row ambiguous."""
        with pytest.raises(SystemExit):
            parser.parse_args(
                [
                    "--phone-number-id",
                    str(uuid.uuid4()),
                    "--number",
                    "+15125550123",
                ]
            )


class TestCredentialHandling:
    """What actually reaches the database."""

    def test_minted_token_carries_the_expected_prefix(self) -> None:
        assert generate_mac_relay_token().startswith(TOKEN_PREFIX)

    def test_stored_value_is_a_digest_not_the_token(self) -> None:
        """The column holds a SHA-256 hex digest, never the plaintext."""
        token = generate_mac_relay_token()
        digest = hash_mac_relay_token(token)

        assert digest != token
        assert not digest.startswith(TOKEN_PREFIX)
        assert len(digest) == 64
        assert int(digest, 16) >= 0  # hex

    def test_hashing_is_deterministic_so_lookup_resolves(self) -> None:
        token = generate_mac_relay_token()
        assert hash_mac_relay_token(token) == hash_mac_relay_token(token)

    def test_distinct_tokens_do_not_collide(self) -> None:
        assert hash_mac_relay_token(generate_mac_relay_token()) != hash_mac_relay_token(
            generate_mac_relay_token()
        )
