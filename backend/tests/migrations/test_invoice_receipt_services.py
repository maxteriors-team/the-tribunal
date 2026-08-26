"""Contract tests for the nullable receipt service-summary migration."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import sqlalchemy as sa

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20260825_invoice_receipt_services.py"
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("invoice_receipt_services", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_migration()


def test_upgrade_adds_nullable_service_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    added: list[tuple[str, sa.Column[Any]]] = []
    monkeypatch.setattr(
        migration.op,
        "add_column",
        lambda table, column: added.append((table, column)),
    )

    migration.upgrade()

    assert len(added) == 1
    table, column = added[0]
    assert table == "invoice_payment_receipt_outbox"
    assert column.name == "service_summary"
    assert isinstance(column.type, sa.Text)
    assert column.nullable is True


def test_downgrade_drops_only_service_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    dropped: list[tuple[str, str]] = []
    monkeypatch.setattr(
        migration.op,
        "drop_column",
        lambda table, column: dropped.append((table, column)),
    )

    migration.downgrade()

    assert dropped == [("invoice_payment_receipt_outbox", "service_summary")]


def test_migration_follows_receipt_outbox_head() -> None:
    assert migration.down_revision == "20260825_invoice_receipt_outbox"
