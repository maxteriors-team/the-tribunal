"""Contract tests for the expand-only Quo single-inbox migration."""

from __future__ import annotations

import importlib.util
from contextlib import nullcontext
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2] / "alembic" / "versions" / "20260826_quo_single_inbox.py"
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("quo_single_inbox", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_migration()


def test_upgrade_adds_constrained_attempts_and_concurrent_partial_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_tables: list[tuple[tuple[object, ...], dict[str, object]]] = []
    created_indexes: list[tuple[tuple[object, ...], dict[str, object]]] = []
    dropped_constraints: list[tuple[tuple[object, ...], dict[str, object]]] = []
    context = MagicMock()
    context.autocommit_block.return_value = nullcontext()
    monkeypatch.setattr(migration.op, "get_context", lambda: context)
    monkeypatch.setattr(
        migration.op,
        "create_table",
        lambda *args, **kwargs: created_tables.append((args, kwargs)),
    )
    monkeypatch.setattr(
        migration.op,
        "create_index",
        lambda *args, **kwargs: created_indexes.append((args, kwargs)),
    )
    monkeypatch.setattr(
        migration.op,
        "drop_constraint",
        lambda *args, **kwargs: dropped_constraints.append((args, kwargs)),
    )

    migration.upgrade()

    assert len(created_tables) == 1
    table_args, table_kwargs = created_tables[0]
    assert table_args[0] == "quo_send_attempts"
    assert table_kwargs["if_not_exists"] is True
    columns = {item.name: item for item in table_args[1:] if isinstance(item, sa.Column)}
    assert set(columns) == {
        "id",
        "workspace_id",
        "conversation_id",
        "client_request_id",
        "state",
        "provider_message_id",
        "message_id",
        "error_class",
        "created_at",
        "updated_at",
    }
    assert columns["workspace_id"].nullable is False
    assert columns["conversation_id"].nullable is False
    assert columns["client_request_id"].nullable is False
    assert "body" not in columns
    assert "phone_number" not in columns

    foreign_keys = [item for item in table_args if isinstance(item, sa.ForeignKeyConstraint)]
    assert {
        tuple(key.target_fullname for key in constraint.elements) for constraint in foreign_keys
    } == {
        ("workspaces.id",),
        ("conversations.id",),
        ("messages.id",),
    }
    unique_names = {
        constraint.name for constraint in table_args if isinstance(constraint, sa.UniqueConstraint)
    }
    assert unique_names == {
        "uq_quo_send_attempts_workspace_request",
        "uq_quo_send_attempts_message",
    }

    assert len(created_indexes) == 2
    indexes = {args[0]: (args, kwargs) for args, kwargs in created_indexes}
    quo_args, quo_kwargs = indexes["uq_messages_quo_provider"]
    assert quo_args == (
        "uq_messages_quo_provider",
        "messages",
        ["source_provider", "provider_message_id"],
    )
    assert quo_kwargs["unique"] is True
    assert quo_kwargs["postgresql_concurrently"] is True
    assert quo_kwargs["if_not_exists"] is True
    quo_predicate = str(quo_kwargs["postgresql_where"])
    assert "source_provider = 'quo'" in quo_predicate
    assert "provider_message_id IS NOT NULL" in quo_predicate

    legacy_args, legacy_kwargs = indexes["uq_messages_legacy_provider_message_id"]
    assert legacy_args == (
        "uq_messages_legacy_provider_message_id",
        "messages",
        ["provider_message_id"],
    )
    assert legacy_kwargs["unique"] is True
    assert legacy_kwargs["postgresql_concurrently"] is True
    assert legacy_kwargs["if_not_exists"] is True
    assert "IS DISTINCT FROM 'quo'" in str(legacy_kwargs["postgresql_where"])
    assert dropped_constraints == [
        (
            ("uq_messages_provider_message_id", "messages"),
            {"type_": "unique", "if_exists": True},
        )
    ]
    context.autocommit_block.assert_called_once_with()


def test_downgrade_drops_index_concurrently_before_attempt_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operations: list[tuple[str, object]] = []
    context = MagicMock()
    context.autocommit_block.return_value = nullcontext()
    monkeypatch.setattr(migration.op, "get_context", lambda: context)
    monkeypatch.setattr(
        migration.op,
        "create_index",
        lambda *args, **kwargs: operations.append(("create_index", (args, kwargs))),
    )
    monkeypatch.setattr(
        migration.op,
        "execute",
        lambda statement: operations.append(("execute", str(statement))),
    )
    monkeypatch.setattr(
        migration.op,
        "drop_index",
        lambda name, **kwargs: operations.append(("drop_index", (name, kwargs))),
    )
    monkeypatch.setattr(
        migration.op,
        "drop_table",
        lambda name: operations.append(("table", name)),
    )

    migration.downgrade()

    assert operations == [
        (
            "create_index",
            (
                (
                    "uq_messages_provider_message_id_restore",
                    "messages",
                    ["provider_message_id"],
                ),
                {
                    "unique": True,
                    "postgresql_concurrently": True,
                    "if_not_exists": True,
                },
            ),
        ),
        (
            "execute",
            "ALTER TABLE messages ADD CONSTRAINT uq_messages_provider_message_id "
            "UNIQUE USING INDEX uq_messages_provider_message_id_restore",
        ),
        (
            "drop_index",
            (
                "uq_messages_quo_provider",
                {
                    "table_name": "messages",
                    "postgresql_concurrently": True,
                    "if_exists": True,
                },
            ),
        ),
        (
            "drop_index",
            (
                "uq_messages_legacy_provider_message_id",
                {
                    "table_name": "messages",
                    "postgresql_concurrently": True,
                    "if_exists": True,
                },
            ),
        ),
        ("table", "quo_send_attempts"),
    ]
    assert context.autocommit_block.call_count == 2
