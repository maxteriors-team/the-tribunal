"""Contract tests for the nullable CRM provenance migration."""

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
    / "20260826_crm_conversation_provenance.py"
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("crm_conversation_provenance", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_migration()


def test_upgrade_only_adds_nullable_provenance_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    added: list[tuple[str, sa.Column[object]]] = []
    monkeypatch.setattr(
        migration.op,
        "add_column",
        lambda table, column: added.append((table, column)),
    )

    migration.upgrade()

    assert [(table, column.name) for table, column in added] == [
        ("conversations", "source_provider"),
        ("messages", "source_provider"),
        ("messages", "external_url"),
    ]
    assert all(column.nullable for _, column in added)
    assert all(column.server_default is None for _, column in added)
    assert [column.type.length for _, column in added] == [50, 50, 2048]


def test_downgrade_removes_only_provenance_columns(monkeypatch: pytest.MonkeyPatch) -> None:
    dropped: list[tuple[str, str]] = []
    monkeypatch.setattr(
        migration.op,
        "drop_column",
        lambda table, column: dropped.append((table, column)),
    )

    migration.downgrade()

    assert dropped == [
        ("messages", "external_url"),
        ("messages", "source_provider"),
        ("conversations", "source_provider"),
    ]
