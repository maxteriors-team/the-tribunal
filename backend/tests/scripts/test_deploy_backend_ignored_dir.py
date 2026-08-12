"""Guards the deploy script against uploading from a gitignored checkout.

``railway up`` filters the upload through gitignore rules. Deploying from a
directory an enclosing repository ignores therefore sends a stripped tarball:
Railway builds it from cached layers, reports SUCCESS, and production keeps
serving the previous image while ``/version`` reports ``"unknown"`` because the
build stamp never arrived. Nothing in the output says so.

That is not hypothetical. ``.gitignore`` lists ``.worktrees/``, and a deploy
launched from a worktree checkout reported success while leaving production on
the previous release.

The detail these tests exist to pin: asked from *inside* such a checkout, git
answers "not ignored" — a linked worktree is the root of its own working tree
and never consults the main repo's ``.gitignore``. A guard written the obvious
way (``git check-ignore "$PWD"`` from the deploy directory) therefore passes
happily and catches nothing. ``test_deploy_dir_reports_itself_as_not_ignored``
pins that trap so the guard is never "simplified" into uselessness.

The stub ``railway`` on PATH is what makes these safe to run in CI: no test
here can reach the real CLI, and asserting the stub was *not* invoked proves
the abort happened before any upload.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

# backend/tests/scripts/<this file> -> repo root -> scripts/ops/deploy_backend.sh
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEPLOY_SCRIPT = _REPO_ROOT / "scripts" / "ops" / "deploy_backend.sh"

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
    # A developer's global gitignore/hooks must not change what these assert.
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
}


def _git(*args: str, cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env={**os.environ, **_GIT_ENV},
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


@pytest.fixture
def railway_stub(tmp_path: Path) -> Path:
    """A fake ``railway`` on PATH that records its arguments instead of deploying.

    Its call log doubles as the assertion that matters: an empty log means the
    script aborted before attempting an upload.
    """
    bin_dir = tmp_path / "stubbin"
    bin_dir.mkdir()
    call_log = bin_dir / "railway-calls.txt"
    stub = bin_dir / "railway"
    stub.write_text(f'#!/bin/sh\necho "$@" >> "{call_log}"\nexit 0\n')
    stub.chmod(0o755)
    return call_log


@pytest.fixture
def outer_repo(tmp_path: Path) -> Path:
    """A repo that ignores ``.worktrees/``, carrying the real deploy script."""
    repo = tmp_path / "outer"
    (repo / "scripts" / "ops").mkdir(parents=True)
    # The script writes its build stamp here; the path must exist.
    (repo / "backend" / "app").mkdir(parents=True)
    (repo / "backend" / "app" / "main.py").write_text("# placeholder\n")
    (repo / ".gitignore").write_text(".worktrees/\nscratch/\n")

    shutil.copy2(_DEPLOY_SCRIPT, repo / "scripts" / "ops" / "deploy_backend.sh")
    (repo / "scripts" / "ops" / "deploy_backend.sh").chmod(0o755)

    _git("init", "-q", "-b", "main", ".", cwd=repo)
    _git("add", "-A", cwd=repo)
    _git("commit", "-qm", "init", cwd=repo)
    return repo


def _run_deploy(cwd: Path, call_log: Path, **env: str) -> subprocess.CompletedProcess[str]:
    """Run the copied deploy script from ``cwd`` with the stubbed CLI on PATH."""
    return subprocess.run(
        [str(cwd / "scripts" / "ops" / "deploy_backend.sh")],
        cwd=cwd,
        env={
            **os.environ,
            **_GIT_ENV,
            "PATH": f"{call_log.parent}{os.pathsep}{os.environ['PATH']}",
            **env,
        },
        capture_output=True,
        text=True,
    )


def test_deploy_dir_reports_itself_as_not_ignored(outer_repo: Path) -> None:
    """The trap this guard exists to survive.

    A linked worktree never consults the main repo's ``.gitignore``, so the
    obvious implementation of this check answers "not ignored" for precisely
    the directory that breaks deploys. If this ever starts failing, git changed
    and the guard can be simplified; until then it must ask the main worktree.
    """
    worktree = outer_repo / ".worktrees" / "wt"
    _git("worktree", "add", "-q", "--detach", str(worktree), "HEAD", cwd=outer_repo)

    from_inside = subprocess.run(
        ["git", "check-ignore", "-q", str(worktree)],
        cwd=worktree,
        env={**os.environ, **_GIT_ENV},
        capture_output=True,
    )
    from_main = subprocess.run(
        ["git", "check-ignore", "-q", str(worktree)],
        cwd=outer_repo,
        env={**os.environ, **_GIT_ENV},
        capture_output=True,
    )

    assert from_inside.returncode == 1, "worktree unexpectedly reported itself ignored"
    assert from_main.returncode == 0, "main worktree should report the checkout ignored"


def test_refuses_to_deploy_from_a_gitignored_worktree(
    outer_repo: Path, railway_stub: Path
) -> None:
    """The real failure: a deploy that reports success and changes nothing."""
    worktree = outer_repo / ".worktrees" / "wt"
    _git("worktree", "add", "-q", "--detach", str(worktree), "HEAD", cwd=outer_repo)

    result = _run_deploy(worktree, railway_stub)

    assert result.returncode != 0, result.stdout
    assert "gitignored" in result.stderr
    assert "DEPLOY_ALLOW_IGNORED=1" in result.stderr
    # Nothing was uploaded: the abort happened before `railway up`.
    assert not railway_stub.exists(), f"railway was invoked: {railway_stub.read_text()}"
    # And no build stamp was left behind to be committed by accident.
    assert not (worktree / "backend" / "app" / "build_info.json").exists()


def test_refuses_to_deploy_from_a_clone_inside_an_ignored_directory(
    outer_repo: Path, railway_stub: Path
) -> None:
    """A separate clone in an ignored path is the same failure.

    ``--git-common-dir`` cannot see this one — the clone owns its own ``.git``
    — so the guard has to ask the enclosing repository.
    """
    nested = outer_repo / "scratch" / "clone"
    nested.parent.mkdir(parents=True, exist_ok=True)
    _git("clone", "-q", str(outer_repo), str(nested), cwd=outer_repo)

    result = _run_deploy(nested, railway_stub)

    assert result.returncode != 0, result.stdout
    assert "gitignored" in result.stderr
    assert not railway_stub.exists(), f"railway was invoked: {railway_stub.read_text()}"


def test_clean_checkout_still_reaches_the_upload(outer_repo: Path, railway_stub: Path) -> None:
    """The guard must not block the normal path.

    Reaching the stubbed ``railway up`` is the assertion: a guard that fails
    closed on every checkout would pass the tests above while making the script
    useless.
    """
    result = _run_deploy(outer_repo, railway_stub)

    assert result.returncode == 0, result.stderr
    assert railway_stub.exists(), "clean checkout never reached `railway up`"
    assert "up --service" in railway_stub.read_text()
    # The stamp is written for the upload and removed again by the EXIT trap.
    assert not (outer_repo / "backend" / "app" / "build_info.json").exists()


def test_override_allows_a_deliberate_ignored_deploy(
    outer_repo: Path, railway_stub: Path
) -> None:
    """An escape hatch, because a wrong guard must never be unbypassable."""
    worktree = outer_repo / ".worktrees" / "wt"
    _git("worktree", "add", "-q", "--detach", str(worktree), "HEAD", cwd=outer_repo)

    result = _run_deploy(worktree, railway_stub, DEPLOY_ALLOW_IGNORED="1")

    assert result.returncode == 0, result.stderr
    assert "DEPLOY_ALLOW_IGNORED=1" in result.stdout
    assert railway_stub.exists(), "override should let the upload proceed"
