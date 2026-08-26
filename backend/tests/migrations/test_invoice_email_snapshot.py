"""Contract tests for the expand-only invoice email snapshot migration."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20260825_invoice_email_snapshot.py"
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("invoice_email_snapshot", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_migration()


def test_upgrade_only_adds_nullable_snapshot_columns(monkeypatch: pytest.MonkeyPatch) -> None:
    added: list[tuple[str, sa.Column[object]]] = []
    monkeypatch.setattr(
        migration.op,
        "add_column",
        lambda table, column: added.append((table, column)),
    )

    migration.upgrade()

    assert [table for table, _ in added] == ["invoices", "invoices"]
    assert [column.name for _, column in added] == ["last_emailed_to", "last_emailed_at"]
    assert all(column.nullable for _, column in added)
    assert isinstance(added[0][1].type, sa.Text)
    assert isinstance(added[1][1].type, sa.DateTime)
    assert added[1][1].type.timezone is True


def test_downgrade_removes_only_snapshot_columns(monkeypatch: pytest.MonkeyPatch) -> None:
    dropped: list[tuple[str, str]] = []
    monkeypatch.setattr(
        migration.op,
        "drop_column",
        lambda table, column: dropped.append((table, column)),
    )

    migration.downgrade()

    assert dropped == [
        ("invoices", "last_emailed_at"),
        ("invoices", "last_emailed_to"),
    ]
