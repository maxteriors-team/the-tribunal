"""Contract tests for seasonal quote snapshots and phase-specific jobs."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20260909_add_seasonal_quote_job_phases.py"
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("seasonal_quote_job_phases", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_migration()


class _DuplicateResult:
    @staticmethod
    def scalar_one_or_none() -> int:
        return 1


class _DuplicateBind:
    def __init__(self, statements: list[str]) -> None:
        self.statements = statements

    def execute(self, statement: object) -> _DuplicateResult:
        self.statements.append(str(statement))
        return _DuplicateResult()


def test_upgrade_bounds_lock_and_statement_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    statements: list[str] = []
    monkeypatch.setattr(
        migration.op,
        "execute",
        lambda statement: statements.append(str(statement)),
    )
    monkeypatch.setattr(migration.op, "add_column", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(migration.op, "drop_constraint", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(migration.op, "create_unique_constraint", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(migration.op, "create_check_constraint", lambda *_args, **_kwargs: None)

    migration.upgrade()

    assert statements[:2] == [
        "SET LOCAL lock_timeout = '5s'",
        "SET LOCAL statement_timeout = '60s'",
    ]


def test_downgrade_refuses_to_discard_two_job_quotes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destructive_calls: list[str] = []
    lock_statements: list[str] = []
    monkeypatch.setattr(
        migration.op,
        "get_bind",
        lambda: _DuplicateBind(lock_statements),
    )
    monkeypatch.setattr(
        migration.op,
        "execute",
        lambda statement: lock_statements.append(str(statement)),
    )
    monkeypatch.setattr(
        migration.op,
        "drop_constraint",
        lambda *_args, **_kwargs: destructive_calls.append("drop_constraint"),
    )
    monkeypatch.setattr(
        migration.op,
        "drop_column",
        lambda *_args, **_kwargs: destructive_calls.append("drop_column"),
    )

    with pytest.raises(RuntimeError, match="multiple field-service jobs"):
        migration.downgrade()

    assert any("SHARE ROW EXCLUSIVE" in statement for statement in lock_statements)
    assert destructive_calls == []
