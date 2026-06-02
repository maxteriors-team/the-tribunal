#!/usr/bin/env python3
"""Export the FastAPI OpenAPI schema to ``backend/openapi.json``.

Run locally with::

    cd backend && uv run python scripts/dev/export_openapi.py

Or, once installed as a project script::

    cd backend && uv run export-openapi

CI uses this script together with ``git diff --exit-code backend/openapi.json``
to fail builds when an API change has not been committed alongside the
regenerated schema. That makes "did we change a public contract?" a reviewable
diff rather than a silent surprise.

The output is written deterministically (sorted keys, 2-space indent, trailing
newline, UTF-8) so the same router state always produces the same bytes — no
spurious diffs from dict ordering.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Make ``app`` importable when invoked as ``python scripts/dev/export_openapi.py``.
# This file lives at ``backend/scripts/dev/export_openapi.py``; the backend root
# (the directory containing ``app/`` and ``openapi.json``) is three levels up.
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))


OUTPUT_PATH = _BACKEND_ROOT / "openapi.json"


def export(output_path: Path = OUTPUT_PATH) -> Path:
    """Write the FastAPI OpenAPI schema to ``output_path`` and return the path.

    Imports ``app.main`` lazily so unit tests can call ``export`` with a
    monkeypatched ``sys.path`` without paying the import cost at module load.
    """
    # Local import: ``app.main`` instantiates the FastAPI app at module level,
    # which requires ``SECRET_KEY`` to be set. Importing here keeps the failure
    # mode close to the call site instead of breaking ``--help``-style usage.
    from app.main import app

    schema: dict[str, Any] = app.openapi()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2, sort_keys=True, ensure_ascii=False)
        f.write("\n")

    return output_path


def main() -> int:
    path = export()
    print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
