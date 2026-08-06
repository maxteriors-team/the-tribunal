"""The local-only guard on ``scripts/dev/seed_sales_kpi_demo.py``.

That script mints a workspace **owner account and prints its password**, then
fills the tenant with ~90 fake contacts, quotes and appointments. Pointed at
production it would create a real login with a known credential, and salt live
KPI reporting with fake rows indistinguishable from real ones.

The realistic accident is not ``ENVIRONMENT=production`` — nobody sets that by
hand. It is exporting a production ``DATABASE_URL`` for a migration or a psql
session, forgetting, and running a seeder in the same shell. So both halves are
checked independently, and both fail closed.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

# backend/tests/scripts/<this file> -> scripts/dev/seed_sales_kpi_demo.py
_SEEDER = Path(__file__).resolve().parents[3] / "scripts" / "dev" / "seed_sales_kpi_demo.py"

PROD_URL = "postgresql+asyncpg://postgres:pw@monorail.proxy.rlwy.net:41234/railway"
LOCAL_URL = "postgresql+asyncpg://postgres:pw@localhost:5432/aicrm"


def _load_seeder() -> Any:
    """Import the seed script by path (it lives outside the ``app`` package)."""
    spec = importlib.util.spec_from_file_location("seed_sales_kpi_demo", _SEEDER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def seeder() -> Any:
    return _load_seeder()


class TestEnvironmentGuard:
    @pytest.mark.parametrize("environment", ["production", "staging", "prod", "PRODUCTION"])
    def test_a_deployed_environment_is_refused(
        self, seeder: Any, monkeypatch: pytest.MonkeyPatch, environment: str
    ) -> None:
        monkeypatch.setattr(seeder.settings, "environment", environment)
        monkeypatch.setattr(seeder.settings, "database_url", LOCAL_URL)

        with pytest.raises(seeder.UnsafeTargetError) as excinfo:
            seeder.assert_local_target()

        assert "ENVIRONMENT" in str(excinfo.value)

    @pytest.mark.parametrize("environment", ["development", "local", "test", "testing"])
    def test_local_environments_are_allowed(
        self, seeder: Any, monkeypatch: pytest.MonkeyPatch, environment: str
    ) -> None:
        monkeypatch.setattr(seeder.settings, "environment", environment)
        monkeypatch.setattr(seeder.settings, "database_url", LOCAL_URL)

        seeder.assert_local_target()

    def test_the_guard_matches_the_app_wide_definition_of_local(self, seeder: Any) -> None:
        """One definition of "is this production?", not two that can drift apart."""
        from app.main import _validate_public_urls  # noqa: F401  (import proves the module loads)

        source = (Path(__file__).resolve().parents[2] / "app" / "main.py").read_text(
            encoding="utf-8"
        )
        assert '{"development", "local", "test", "testing"}' in source
        assert {"development", "local", "test", "testing"} == seeder.LOCAL_ENVIRONMENTS


class TestDatabaseHostGuard:
    def test_a_production_host_is_refused_even_in_a_development_environment(
        self, seeder: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The actual accident: local ENVIRONMENT, exported production URL."""
        monkeypatch.setattr(seeder.settings, "environment", "development")
        monkeypatch.setattr(seeder.settings, "database_url", PROD_URL)

        with pytest.raises(seeder.UnsafeTargetError) as excinfo:
            seeder.assert_local_target()

        # Pin the *reason* rather than searching the message for a hostname. The
        # message has to tell an operator why their seed was refused, and an
        # incidental substring match would still pass if it named the wrong host.
        assert "not a recognised local host" in str(excinfo.value)

    def test_a_hostname_hidden_in_the_password_does_not_pass_the_guard(
        self, seeder: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Why this parses the URL instead of searching it for "localhost".

        A substring check against the whole URL is satisfied by a password, a
        database name or a query parameter. This URL points squarely at
        production while containing the word ``localhost``.
        """
        monkeypatch.setattr(seeder.settings, "environment", "development")
        monkeypatch.setattr(
            seeder.settings,
            "database_url",
            "postgresql+asyncpg://postgres:localhost@monorail.proxy.rlwy.net:5432/railway",
        )

        with pytest.raises(seeder.UnsafeTargetError):
            seeder.assert_local_target()

    @pytest.mark.parametrize(
        "url",
        [
            "postgresql+asyncpg://u:p@prod.abc.us-east-1.rds.amazonaws.com:5432/app",
            "postgresql+asyncpg://u:p@db.qwerty.supabase.co:5432/postgres",
            "postgresql+asyncpg://u:p@ep-cool-name.neon.tech:5432/main",
            "postgresql+asyncpg://u:p@10.0.0.5:5432/app",
        ],
    )
    def test_unknown_remote_hosts_fail_closed(
        self, seeder: Any, monkeypatch: pytest.MonkeyPatch, url: str
    ) -> None:
        """An allowlist, so a host nobody thought of is refused rather than seeded."""
        monkeypatch.setattr(seeder.settings, "environment", "development")
        monkeypatch.setattr(seeder.settings, "database_url", url)

        with pytest.raises(seeder.UnsafeTargetError):
            seeder.assert_local_target()

    @pytest.mark.parametrize(
        "host", ["localhost", "127.0.0.1", "host.docker.internal", "aicrm-postgres"]
    )
    def test_recognised_local_hosts_are_allowed(
        self, seeder: Any, monkeypatch: pytest.MonkeyPatch, host: str
    ) -> None:
        monkeypatch.setattr(seeder.settings, "environment", "development")
        monkeypatch.setattr(
            seeder.settings, "database_url", f"postgresql+asyncpg://u:p@{host}:5432/aicrm"
        )

        seeder.assert_local_target()


class TestPassword:
    def test_no_password_is_hardcoded_in_the_source(self) -> None:
        """The finding that started this: a working credential living in git."""
        source = _SEEDER.read_text(encoding="utf-8")

        assert "PASSWORD = " not in source
        assert "SEED_DEMO_PASSWORD" in source

    def test_an_absent_env_var_yields_a_random_password(
        self, seeder: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SEED_DEMO_PASSWORD", raising=False)

        first = seeder._resolve_password()
        second = seeder._resolve_password()

        # Distinct per run, so two seeded demos never share a credential.
        assert first != second
        assert len(first) >= 8

    def test_the_env_var_is_used_verbatim_when_set(
        self, seeder: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SEED_DEMO_PASSWORD", "operator-chosen-pw")

        assert seeder._resolve_password() == "operator-chosen-pw"

    def test_a_password_below_the_app_minimum_is_refused(
        self, seeder: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Silently seeding an account nobody can log into is not a success."""
        monkeypatch.setenv("SEED_DEMO_PASSWORD", "short")

        with pytest.raises(seeder.UnsafeTargetError):
            seeder._resolve_password()


class TestGuardRunsBeforeAnyConnection:
    def test_the_guard_is_called_before_the_session_is_opened(self) -> None:
        """Order matters: a refusal after connecting has already touched the DB."""
        source = _SEEDER.read_text(encoding="utf-8")
        body = source.split("async def main()", 1)[1]

        assert body.index("assert_local_target()") < body.index("AsyncSessionLocal()")
