"""Contract tests for manual cash/check invoice settlement provenance."""

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
    / "20260825_invoice_manual_payment.py"
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("invoice_manual_payment", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_migration()


def test_upgrade_adds_provenance_constraints_and_card_backfill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    columns: list[tuple[str, sa.Column[Any]]] = []
    checks: list[str] = []
    uniques: list[str] = []
    foreign_keys: list[tuple[str, str]] = []
    statements: list[str] = []
    monkeypatch.setattr(
        migration.op,
        "add_column",
        lambda table, column: columns.append((table, column)),
    )
    monkeypatch.setattr(
        migration.op,
        "create_check_constraint",
        lambda name, *_args: checks.append(name),
    )
    monkeypatch.setattr(
        migration.op,
        "create_unique_constraint",
        lambda name, *_args: uniques.append(name),
    )
    monkeypatch.setattr(
        migration.op,
        "create_foreign_key",
        lambda name, source, *_args, **_kwargs: foreign_keys.append((name, source)),
    )
    monkeypatch.setattr(migration.op, "execute", lambda statement: statements.append(statement))

    migration.upgrade()

    assert [column.name for _, column in columns] == [
        "payment_method",
        "payment_recorded_by_id",
        "manual_payment_amount",
        "manual_payment_reference",
        "manual_payment_idempotency_key",
    ]
    assert all(table == "invoices" for table, _ in columns)
    assert checks == ["ck_invoices_payment_method", "ck_invoices_manual_payment_amount"]
    assert uniques == ["uq_invoices_manual_payment_idempotency_key"]
    assert foreign_keys == [("fk_invoices_payment_recorded_by_id_users", "invoices")]
    assert statements == ["UPDATE invoices SET payment_method = 'card' WHERE paid_at IS NOT NULL"]


def test_migration_follows_receipt_services_head() -> None:
    assert migration.down_revision == "20260825_receipt_services"
