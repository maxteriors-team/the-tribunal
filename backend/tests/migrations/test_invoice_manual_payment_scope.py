"""Contract tests for workspace-scoped manual-payment idempotency."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20260825_invoice_manual_payment_scope.py"
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("invoice_manual_payment_scope", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_migration()


def test_upgrade_replaces_global_key_with_workspace_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dropped: list[str] = []
    created: list[tuple[str, list[str]]] = []
    statements: list[str] = []
    monkeypatch.setattr(
        migration.op,
        "drop_constraint",
        lambda name, *_args, **_kwargs: dropped.append(name),
    )
    monkeypatch.setattr(
        migration.op,
        "create_unique_constraint",
        lambda name, _table, columns: created.append((name, columns)),
    )
    monkeypatch.setattr(migration.op, "execute", lambda statement: statements.append(statement))

    migration.upgrade()

    assert dropped == ["uq_invoices_manual_payment_idempotency_key"]
    assert created == [
        (
            "uq_invoices_manual_payment_idempotency_key",
            ["workspace_id", "manual_payment_idempotency_key"],
        )
    ]
    assert "stripe_payment_intent_id IS NULL" in statements[0]
    assert "manual_payment_idempotency_key IS NULL" in statements[0]


def test_downgrade_rekeys_cross_workspace_duplicates_before_global_constraint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[list[str]] = []
    statements: list[str] = []
    monkeypatch.setattr(migration.op, "drop_constraint", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        migration.op,
        "create_unique_constraint",
        lambda _name, _table, columns: created.append(columns),
    )
    monkeypatch.setattr(migration.op, "execute", lambda statement: statements.append(statement))

    migration.downgrade()

    assert "gen_random_uuid()" in statements[0]
    assert created == [["manual_payment_idempotency_key"]]
    assert statements[-1] == "UPDATE invoices SET payment_method = 'card' WHERE paid_at IS NOT NULL"


def test_migration_follows_manual_payment_revision() -> None:
    assert migration.down_revision == "20260825_invoice_manual_pay"
