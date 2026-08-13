"""Real-world webhook payload fixtures.

Each JSON file in ``telnyx/`` is shaped after the actual HTTP body Telnyx
delivers to ``/webhooks/telnyx/sms`` and ``/webhooks/telnyx/voice``. They are kept
as data files (not Python literals) so the same payloads can be replayed
manually with curl while debugging webhook regressions.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

FIXTURES_DIR = Path(__file__).parent


def load_fixture(*parts: str) -> dict[str, Any]:
    """Load a JSON fixture by path parts relative to this package.

    Example:
        ``load_fixture("telnyx", "call_initiated.json")``
    """
    path = FIXTURES_DIR.joinpath(*parts)
    with path.open(encoding="utf-8") as fh:
        loaded = json.load(fh)
    return cast("dict[str, Any]", loaded)


def load_telnyx_payload(filename: str) -> dict[str, Any]:
    """Load a Telnyx webhook fixture and return ``data.payload``."""
    return cast(
        "dict[str, Any]",
        load_fixture("telnyx", filename)["data"]["payload"],
    )
