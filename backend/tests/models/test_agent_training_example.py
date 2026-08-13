"""Model contract tests for human-approved agent training examples."""

import sqlalchemy as sa

from app.core.encryption import EncryptedString
from app.models import AgentTrainingExample


def test_training_example_encrypts_all_conversation_text() -> None:
    table = AgentTrainingExample.__table__

    for column_name in (
        "customer_message",
        "ai_response",
        "ideal_response",
        "operator_note",
    ):
        assert isinstance(table.c[column_name].type, EncryptedString)


def test_training_example_tenant_and_deletion_contract() -> None:
    table = AgentTrainingExample.__table__
    foreign_keys = {
        column.name: next(iter(column.foreign_keys))
        for column in (
            table.c.workspace_id,
            table.c.agent_id,
            table.c.conversation_id,
            table.c.source_message_id,
            table.c.created_by_user_id,
        )
    }

    assert foreign_keys["workspace_id"].ondelete == "CASCADE"
    assert foreign_keys["agent_id"].ondelete == "CASCADE"
    assert foreign_keys["conversation_id"].ondelete == "SET NULL"
    assert foreign_keys["source_message_id"].ondelete == "SET NULL"
    assert foreign_keys["created_by_user_id"].ondelete == "SET NULL"
    assert table.c.workspace_id.nullable is False
    assert table.c.agent_id.nullable is False


def test_training_example_allows_one_correction_per_source_message() -> None:
    constraint = next(
        item
        for item in AgentTrainingExample.__table__.constraints
        if item.name == "uq_agent_training_examples_source_message_id"
    )

    assert isinstance(constraint, sa.UniqueConstraint)
    assert [column.name for column in constraint.columns] == ["source_message_id"]
    assert "AgentTrainingExample" in __import__("app.models", fromlist=["__all__"]).__all__
