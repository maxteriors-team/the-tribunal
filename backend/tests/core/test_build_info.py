"""Resolution order and failure modes for the deployed-commit lookup.

``/version`` is the fastest way to answer "did my deploy land?" mid-incident,
so the contract worth pinning is not just "returns a string" but *which* source
wins and what happens when a source is present-but-broken. Every test isolates
the environment and redirects the stamp path at ``tmp_path`` so a real stamp
left behind by an interrupted deploy cannot make these pass or fail by
accident.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core import build_info
from app.core.build_info import UNKNOWN_SHA, resolve_build_info

# Captured at import, before the autouse fixture redirects it at tmp_path, so
# TestStampLocation can assert the real shipped path.
REAL_STAMP_PATH = build_info.BUILD_STAMP_PATH

RAILWAY_SHA = "d0beb8f5c55b36df7d674d55965a23b8d54ad69b"
BUILD_ARG_SHA = "1111111111111111111111111111111111111111"
STAMP_SHA = "2222222222222222222222222222222222222222"


@pytest.fixture(autouse=True)
def isolated_build_sources(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Clear both env vars and point the stamp at an absent temp file.

    Returns the stamp path so tests can materialize it when they want it.
    """
    monkeypatch.delenv(build_info.RAILWAY_SHA_ENV, raising=False)
    monkeypatch.delenv(build_info.BUILD_SHA_ENV, raising=False)
    stamp_path = tmp_path / "build_info.json"
    monkeypatch.setattr(build_info, "BUILD_STAMP_PATH", stamp_path)
    return stamp_path


def _write_stamp(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


class TestResolutionOrder:
    """First non-blank source wins, in a fixed precedence."""

    def test_railway_env_wins_over_everything(
        self, monkeypatch: pytest.MonkeyPatch, isolated_build_sources: Path
    ) -> None:
        """A git-triggered build keeps reporting Railway's SHA, unchanged."""
        monkeypatch.setenv(build_info.RAILWAY_SHA_ENV, RAILWAY_SHA)
        monkeypatch.setenv(build_info.BUILD_SHA_ENV, BUILD_ARG_SHA)
        _write_stamp(isolated_build_sources, {"sha": STAMP_SHA})

        assert resolve_build_info() == (RAILWAY_SHA, "railway_git_env")

    def test_build_arg_env_wins_over_stamp(
        self, monkeypatch: pytest.MonkeyPatch, isolated_build_sources: Path
    ) -> None:
        """``docker build --build-arg BUILD_COMMIT_SHA`` outranks the stamp."""
        monkeypatch.setenv(build_info.BUILD_SHA_ENV, BUILD_ARG_SHA)
        _write_stamp(isolated_build_sources, {"sha": STAMP_SHA})

        assert resolve_build_info() == (BUILD_ARG_SHA, "build_env")

    def test_stamp_used_when_no_env_is_set(self, isolated_build_sources: Path) -> None:
        """The ``railway up`` path: no env vars exist, only the baked stamp."""
        _write_stamp(isolated_build_sources, {"sha": STAMP_SHA})

        assert resolve_build_info() == (STAMP_SHA, "build_stamp")

    def test_stamp_dirty_suffix_is_preserved(self, isolated_build_sources: Path) -> None:
        """A ``-dirty`` deploy must not be laundered into a clean SHA."""
        _write_stamp(isolated_build_sources, {"sha": f"{STAMP_SHA}-dirty"})

        sha, source = resolve_build_info()
        assert sha == f"{STAMP_SHA}-dirty"
        assert source == "build_stamp"

    def test_falls_back_to_unknown(self) -> None:
        """Local dev and tests: no env, no stamp — behaviour is unchanged."""
        assert resolve_build_info() == (UNKNOWN_SHA, "unknown")


class TestBlankAndBrokenSources:
    """A present-but-useless source must fall through, never crash or lie."""

    @pytest.mark.parametrize("blank", ["", "   ", "\n"])
    def test_blank_railway_env_falls_through_to_stamp(
        self, monkeypatch: pytest.MonkeyPatch, isolated_build_sources: Path, blank: str
    ) -> None:
        """Railway injects empty strings for unset vars in some contexts."""
        monkeypatch.setenv(build_info.RAILWAY_SHA_ENV, blank)
        _write_stamp(isolated_build_sources, {"sha": STAMP_SHA})

        assert resolve_build_info() == (STAMP_SHA, "build_stamp")

    def test_surrounding_whitespace_is_stripped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(build_info.RAILWAY_SHA_ENV, f"  {RAILWAY_SHA}\n")

        assert resolve_build_info() == (RAILWAY_SHA, "railway_git_env")

    def test_malformed_stamp_json_yields_unknown(self, isolated_build_sources: Path) -> None:
        """A truncated write must not 500 the probe you reach for in an incident."""
        isolated_build_sources.write_text('{"sha": "abc12', encoding="utf-8")

        assert resolve_build_info() == (UNKNOWN_SHA, "unknown")

    @pytest.mark.parametrize("payload", [{"commit": STAMP_SHA}, {"sha": 12345}, {"sha": "  "}, []])
    def test_unusable_stamp_payload_yields_unknown(
        self, isolated_build_sources: Path, payload: object
    ) -> None:
        """Missing key, wrong type, blank value, or a non-object all fall back."""
        _write_stamp(isolated_build_sources, payload)

        assert resolve_build_info() == (UNKNOWN_SHA, "unknown")

    def test_unreadable_stamp_yields_unknown(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A directory (or any OSError) where the stamp should be is survivable."""
        stamp_dir = tmp_path / "build_info.json"
        stamp_dir.mkdir()
        monkeypatch.setattr(build_info, "BUILD_STAMP_PATH", stamp_dir)

        assert resolve_build_info() == (UNKNOWN_SHA, "unknown")


class TestStampLocation:
    """The stamp path has to match what the deploy script writes."""

    def test_stamp_lives_inside_the_app_package(self) -> None:
        """``backend/app/build_info.json`` — copied by nixpacks and the Dockerfile.

        Resolved from ``__file__`` rather than the working directory because
        uvicorn's cwd differs between local dev, the Docker image, and nixpacks.
        """
        import app as app_package

        expected = Path(app_package.__file__).resolve().parent / "build_info.json"
        assert expected == REAL_STAMP_PATH
