#!/usr/bin/env python3
"""Apply the browser CORS rule the light designer needs to the media bucket.

Lighting-project images live in the private bucket and are handed to the browser
as short-lived presigned URLs. The designer draws those images onto a canvas and
calls ``toDataURL()`` to export a proposal JPEG, which means the image must be
loaded with ``crossOrigin="anonymous"`` — and that only works if the bucket
answers with ``Access-Control-Allow-Origin``. Without this rule the image fails
to load and design export silently breaks.

Allowed origins mirror ``CORS_ORIGINS`` so there is one list to update, not two.
Re-run this after any domain change (see CLAUDE.md, "When the domain changes").

Run against production with the service's own credentials:

    cd backend && railway run --service the-tribunal-api -- \\
        uv run python ../scripts/ops/set_bucket_cors.py --apply
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings  # noqa: E402
from app.services.messaging.media_storage import MMSMediaStorage  # noqa: E402


def _browser_origins() -> list[str]:
    """The http(s) origins a browser may read bucket objects from."""
    origins = [origin.strip() for origin in settings.cors_origins if origin.strip()]
    # A wildcard would let any site read a leaked presigned URL from script.
    return [origin for origin in origins if origin != "*" and origin.startswith("http")]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the rule; omitted means print the current and intended rule only",
    )
    args = parser.parse_args()

    if not settings.mms_storage_enabled:
        print("aborted=storage-disabled", file=sys.stderr)
        raise SystemExit(1)

    origins = _browser_origins()
    if not origins:
        print("aborted=no-usable-origins", file=sys.stderr)
        raise SystemExit(1)

    storage = MMSMediaStorage.from_settings()
    print(f"bucket={settings.mms_storage_bucket}")
    print(f"current={storage.get_cors_rules()}")
    print(f"intended={origins}")

    if not args.apply:
        print("result=dry-run")
        return

    storage.put_cors_rules(allowed_origins=origins)
    print(f"applied={storage.get_cors_rules()}")
    print("result=applied")


if __name__ == "__main__":
    main()
