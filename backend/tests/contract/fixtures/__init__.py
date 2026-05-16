"""Real-world, sanitized webhook payload fixtures used by contract tests.

Each JSON file in ``telnyx/``, ``calcom/``, and ``resend/`` matches the
exact HTTP body the provider delivers to the corresponding webhook
endpoint. Payloads are kept as data files (not Python literals) so the
same bytes can be replayed manually with curl while debugging webhook
regressions.

Helpers in this module load a fixture by path and return the parsed JSON
as a plain ``dict[str, Any]``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

FIXTURES_DIR = Path(__file__).parent


def load_fixture(provider: str, filename: str) -> dict[str, Any]:
    """Load a JSON fixture for *provider* (``"telnyx"``/``"calcom"``/``"resend"``).

    Example:
        ``load_fixture("calcom", "booking_created.json")``
    """
    path = FIXTURES_DIR / provider / filename
    with path.open(encoding="utf-8") as fh:
        loaded = json.load(fh)
    return cast("dict[str, Any]", loaded)
