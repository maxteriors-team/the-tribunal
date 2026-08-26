"""Contract tests for the expand-only invoice receipt outbox migration."""

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
    / "20260825_invoice_receipt_outbox.py"
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("invoice_receipt_outbox", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_migration()


def test_upgrade_only_creates_outbox_table_and_indexes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tables: list[tuple[str, tuple[Any, ...]]] = []
    indexes: list[tuple[str, str, tuple[str, ...], bool]] = []
    monkeypatch.setattr(
        migration.op,
        "create_table",
        lambda name, *items: tables.append((name, items)),
    )
    monkeypatch.setattr(
        migration.op,
        "create_index",
        lambda name, table, columns, unique=False: indexes.append(
            (name, table, tuple(columns), unique)
        ),
    )

    migration.upgrade()

    assert [name for name, _ in tables] == ["invoice_payment_receipt_outbox"]
    columns = {item.name: item for item in tables[0][1] if isinstance(item, sa.Column)}
    assert columns["payment_event_id"].nullable is False
    assert columns["recipient_email"].nullable is True
    assert columns["next_attempt_at"].nullable is False
    assert columns["last_error"].type.length == 1000
    constraints = {item.name for item in tables[0][1] if isinstance(item, sa.Constraint)}
    assert "uq_invoice_receipt_outbox_invoice_event" in constraints
    assert "ck_invoice_payment_receipt_outbox_attempt_count" in constraints
    assert indexes == [
        (
            "ix_invoice_payment_receipt_outbox_workspace_id",
            "invoice_payment_receipt_outbox",
            ("workspace_id",),
            False,
        ),
        (
            "ix_invoice_receipt_outbox_due",
            "invoice_payment_receipt_outbox",
            ("status", "next_attempt_at"),
            False,
        ),
    ]


def test_migration_follows_invoice_email_snapshot_head() -> None:
    assert migration.down_revision == "20260825_invoice_email_snapshot"
