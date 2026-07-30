"""Guards against a script that runs against the wrong database and says nothing.

``_promote_env_database_url`` only takes effect if nothing has imported
``app.core.config`` yet, because ``settings`` is a module-level singleton and
``app.db.session`` builds ``engine``/``AsyncSessionLocal`` from it at import
time. A script that imports ``app.db.session`` at module scope — the obvious way
to write one — therefore froze the *local* URL before ``bootstrap()`` ran, so
``--env production`` read and wrote the developer's dev database while every log
line claimed production.

The seed script did exactly that: pointed at an unreachable production host it
still reported ``workspaces=2030`` from the local database and exited 0.

These tests pin the resolution rules, and the last one pins the behaviour that
actually matters: an unreachable production URL must fail, not quietly succeed
against localhost.
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts._harness import (
    Env,
    ExecutionContext,
    ScriptAbortError,
    redact_database_url,
    run,
    script_database_url,
    script_sessionmaker,
)

# backend/tests/scripts/<this file> -> backend/scripts/seeds/seed_product_help.py
_SEEDER = Path(__file__).resolve().parents[2] / "scripts" / "seeds" / "seed_product_help.py"

LOCAL_URL = "postgresql+asyncpg://aicrm:aicrm_dev_password@localhost:5432/aicrm"
# ``.invalid`` is reserved by RFC 6761 and is guaranteed never to resolve, so
# this stands in for "a production host this machine cannot reach".
UNREACHABLE_URL = "postgresql+asyncpg://u:pw@db-prod.invalid:5432/railway"


def _context(env: Env, *, dry_run: bool = True) -> ExecutionContext:
    return ExecutionContext(
        env=env,
        dry_run=dry_run,
        assume_yes=True,
        logger=logging.getLogger("test-seed"),
    )


def _load_seeder() -> Any:
    """Import the seed script by path (it lives outside the ``app`` package)."""
    spec = importlib.util.spec_from_file_location("seed_product_help", _SEEDER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestUrlResolution:
    def test_production_without_an_override_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The ambient DATABASE_URL must never satisfy ``--env production``."""
        monkeypatch.delenv("PRODUCTION_DATABASE_URL", raising=False)
        monkeypatch.setenv("DATABASE_URL", LOCAL_URL)

        with pytest.raises(ScriptAbortError) as excinfo:
            script_database_url(Env.PRODUCTION)

        assert "PRODUCTION_DATABASE_URL" in str(excinfo.value)

    def test_production_pointing_at_localhost_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An override that resolves locally is the silent-fallback shape."""
        monkeypatch.setenv("PRODUCTION_DATABASE_URL", LOCAL_URL)

        with pytest.raises(ScriptAbortError) as excinfo:
            script_database_url(Env.PRODUCTION)

        assert "local host" in str(excinfo.value)

    @pytest.mark.parametrize("host", ["127.0.0.1", "localhost"])
    def test_every_loopback_spelling_is_refused(
        self, monkeypatch: pytest.MonkeyPatch, host: str
    ) -> None:
        monkeypatch.setenv(
            "PRODUCTION_DATABASE_URL", f"postgresql+asyncpg://u:pw@{host}:5432/aicrm"
        )

        with pytest.raises(ScriptAbortError):
            script_database_url(Env.PRODUCTION)

    def test_remote_override_is_honoured_verbatim(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The resolved URL is the override — not whatever DATABASE_URL says."""
        monkeypatch.setenv("PRODUCTION_DATABASE_URL", UNREACHABLE_URL)
        monkeypatch.setenv("DATABASE_URL", LOCAL_URL)

        resolved = script_database_url(Env.PRODUCTION)

        assert "db-prod.invalid" in resolved
        assert "localhost" not in resolved

    def test_railway_style_url_is_coerced_onto_asyncpg(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Railway hands out ``postgresql://``; asyncpg needs the driver spelled out."""
        monkeypatch.setenv(
            "PRODUCTION_DATABASE_URL", "postgresql://u:pw@db-prod.invalid:5432/railway"
        )

        assert script_database_url(Env.PRODUCTION).startswith("postgresql+asyncpg://")

    def test_local_may_still_use_the_ambient_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LOCAL_DATABASE_URL", raising=False)
        monkeypatch.setenv("DATABASE_URL", LOCAL_URL)

        assert script_database_url(Env.LOCAL) == LOCAL_URL

    def test_the_password_is_never_logged(self) -> None:
        redacted = redact_database_url(UNREACHABLE_URL)

        assert "pw" not in redacted
        assert "db-prod.invalid" in redacted


class TestSessionFactoryBinding:
    @pytest.mark.asyncio
    async def test_engine_binds_the_resolved_host_not_the_imported_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The engine is created on call, so import order cannot rebind it.

        ``app.db.session`` is imported below *before* the factory is built,
        reproducing the ordering that used to defeat the override.
        """
        import app.db.session as app_session

        assert app_session.engine.url.host == "localhost", "precondition: app engine is local"

        monkeypatch.setenv("PRODUCTION_DATABASE_URL", UNREACHABLE_URL)

        async with script_sessionmaker(_context(Env.PRODUCTION)) as factory:
            bound = factory.kw["bind"]
            assert bound.url.host == "db-prod.invalid"
            assert bound.url.database == "railway"


class TestSeederEndToEnd:
    def test_seeder_does_not_use_the_import_time_session(self) -> None:
        """A regression pin on the specific import that caused the bug."""
        source = _SEEDER.read_text(encoding="utf-8")

        assert "AsyncSessionLocal" not in source.split("# NOTE:")[-1].split("\n", 4)[-1]
        assert "script_sessionmaker" in source

    def test_unreachable_production_url_fails_instead_of_seeding_localhost(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The whole point: exit non-zero rather than succeed on the wrong database.

        This assertion is only meaningful because a localhost fallback would
        *work* — the dev database is reachable in development and would report a
        real workspace count and exit 0. A non-zero exit therefore proves the run
        went to ``db-prod.invalid`` and nowhere else.
        """
        monkeypatch.setenv("PRODUCTION_DATABASE_URL", UNREACHABLE_URL)
        monkeypatch.setenv("DATABASE_URL", LOCAL_URL)
        monkeypatch.setattr(
            sys, "argv", ["seed_product_help.py", "--env", "production", "--dry-run", "--yes"]
        )

        seeder = _load_seeder()
        exit_code = run(seeder.main)

        assert exit_code != 0

    def test_missing_override_aborts_rather_than_crashing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A refused target is an abort, not "seeded nothing"."""
        monkeypatch.delenv("PRODUCTION_DATABASE_URL", raising=False)
        monkeypatch.setattr(sys, "argv", ["seed_product_help.py", "--env", "production", "--yes"])

        seeder = _load_seeder()
        exit_code = run(seeder.main)

        assert exit_code == 3
