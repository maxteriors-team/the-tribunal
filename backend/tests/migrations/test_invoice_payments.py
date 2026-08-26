"""Contract tests for the append-only invoice payment ledger migration."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2] / "alembic" / "versions" / "20260826_invoice_payments.py"
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("invoice_payments", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_migration()


def test_upgrade_creates_ledger_backfills_and_adds_receipt_balance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tables: list[str] = []
    indexes: list[str] = []
    statements: list[str] = []
    columns: list[tuple[str, str]] = []
    monkeypatch.setattr(
        migration.op,
        "create_table",
        lambda name, *_args, **_kwargs: tables.append(name),
    )
    monkeypatch.setattr(
        migration.op,
        "create_index",
        lambda name, *_args, **_kwargs: indexes.append(name),
    )
    monkeypatch.setattr(migration.op, "execute", lambda statement: statements.append(statement))
    monkeypatch.setattr(
        migration.op,
        "add_column",
        lambda table, column: columns.append((table, column.name)),
    )

    migration.upgrade()

    assert tables == ["invoice_payments"]
    assert indexes == ["ix_invoice_payments_workspace_invoice"]
    assert "FROM invoices WHERE amount_paid > 0" in statements[0]
    assert "ROW_NUMBER() OVER (PARTITION BY stripe_payment_intent_id" in statements[0]
    assert columns == [("invoice_payment_receipt_outbox", "balance_remaining")]


def test_migration_follows_manual_payment_scope() -> None:
    assert migration.down_revision == "20260825_manual_pay_scope"
