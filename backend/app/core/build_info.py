"""Resolve the commit SHA of the running build.

``/version`` exists to answer one question mid-incident: *which commit is
live?* Railway only injects ``RAILWAY_GIT_COMMIT_SHA`` for deploys that
originated from a GitHub trigger. This backend is deployed manually with
``railway up`` (see the release process in ``CLAUDE.md``), which uploads a
tarball of ``backend/`` carrying no git metadata — ``.railwayignore`` excludes
``.git/`` and the builder has no repo to interrogate. So that variable is never
set in production and the endpoint reported ``"unknown"`` forever, which cost
~10 minutes of "did the build land?" confusion during the 2026-07-27
pool/healthcheck release.

Resolution order (first non-blank wins):

1. ``RAILWAY_GIT_COMMIT_SHA`` — git-triggered Railway builds, unchanged.
2. ``BUILD_COMMIT_SHA`` — generic build-time escape hatch; ``backend/Dockerfile``
   forwards it from ``--build-arg BUILD_COMMIT_SHA=...``.
3. ``app/build_info.json`` — build stamp written by
   ``scripts/ops/deploy_backend.sh`` (``make deploy.backend``) immediately
   before ``railway up`` and deleted right after the upload returns.
4. ``"unknown"`` — local dev and tests, where neither env var nor stamp exists.

Two deliberate constraints on the stamp:

* It lives **inside** the ``app`` package so it travels with the source under
  both builders (nixpacks copies the whole upload to ``/app``; the Dockerfile's
  ``COPY app/ ./app/`` picks it up) and resolves from ``__file__`` rather than
  the process working directory.
* It is **not** in ``.gitignore``. ``railway up`` skips gitignored paths when
  building the upload tarball, so an ignored stamp would never reach the
  builder. The deploy script removes it after upload and a pre-commit hook
  blocks it from being committed, because a stale committed SHA would make
  ``/version`` *lie* — strictly worse than ``"unknown"``.

Nothing here is cached: ``/version`` is a low-traffic probe, and re-reading a
~100-byte file keeps the resolution honest if the stamp changes under a running
process (and keeps tests free of cache-invalidation coupling).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Final, NamedTuple

import structlog

logger = structlog.get_logger()

#: Reported when no source can identify the build.
UNKNOWN_SHA: Final = "unknown"

#: Set by Railway only for deploys originating from a GitHub trigger.
RAILWAY_SHA_ENV: Final = "RAILWAY_GIT_COMMIT_SHA"

#: Generic build-arg/env override for non-Railway or Docker builds.
BUILD_SHA_ENV: Final = "BUILD_COMMIT_SHA"

#: ``backend/app/build_info.json`` — written at deploy time, absent otherwise.
BUILD_STAMP_PATH: Path = Path(__file__).resolve().parents[1] / "build_info.json"


class BuildInfo(NamedTuple):
    """The resolved build identity.

    ``source`` names which resolution step answered, so a ``"unknown"`` reading
    can be diagnosed from the response alone instead of by guesswork.
    """

    sha: str
    source: str


def _clean(value: str | None) -> str | None:
    """Normalize a candidate SHA: blank/whitespace-only counts as absent."""
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _stamp_sha() -> str | None:
    """Read ``sha`` out of the build stamp, or ``None`` if unusable.

    A missing stamp is the normal case (local dev, git-triggered builds) and is
    silent. A stamp that exists but cannot be parsed is a real deploy-tooling
    fault, so it is logged rather than swallowed.
    """
    try:
        raw = BUILD_STAMP_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        logger.warning(
            "build_stamp_unreadable",
            path=str(BUILD_STAMP_PATH),
            error=type(exc).__name__,
        )
        return None

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("build_stamp_malformed", path=str(BUILD_STAMP_PATH))
        return None

    if not isinstance(payload, dict):
        logger.warning("build_stamp_malformed", path=str(BUILD_STAMP_PATH))
        return None

    sha = payload.get("sha")
    if not isinstance(sha, str):
        logger.warning("build_stamp_missing_sha", path=str(BUILD_STAMP_PATH))
        return None

    return _clean(sha)


def resolve_build_info() -> BuildInfo:
    """Return the deployed commit SHA and the source that supplied it."""
    railway_sha = _clean(os.getenv(RAILWAY_SHA_ENV))
    if railway_sha:
        return BuildInfo(railway_sha, "railway_git_env")

    build_arg_sha = _clean(os.getenv(BUILD_SHA_ENV))
    if build_arg_sha:
        return BuildInfo(build_arg_sha, "build_env")

    stamped_sha = _stamp_sha()
    if stamped_sha:
        return BuildInfo(stamped_sha, "build_stamp")

    return BuildInfo(UNKNOWN_SHA, "unknown")
