"""Contract tests for the expand-only Quo voice metadata migration."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2] / "alembic" / "versions" / "20260826_quo_voice_metadata.py"
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("quo_voice_metadata", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_migration()


def test_upgrade_adds_only_nullable_voicemail_indicator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    added: list[tuple[str, sa.Column[object]]] = []
    monkeypatch.setattr(
        migration.op,
        "add_column",
        lambda table, column: added.append((table, column)),
    )

    migration.upgrade()

    assert len(added) == 1
    table, column = added[0]
    assert table == "messages"
    assert column.name == "is_voicemail"
    assert isinstance(column.type, sa.Boolean)
    assert column.nullable is True
    assert column.server_default is not None


def test_downgrade_removes_only_voicemail_indicator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dropped: list[tuple[str, str]] = []
    monkeypatch.setattr(
        migration.op,
        "drop_column",
        lambda table, column: dropped.append((table, column)),
    )

    migration.downgrade()

    assert dropped == [("messages", "is_voicemail")]
