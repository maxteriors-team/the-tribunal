"""Model contracts for durable contact AI memory."""

import sqlalchemy as sa

from app.core.encryption import EncryptedString
from app.models import ContactAIMemory, ContactAIMemoryFact


def test_contact_ai_memory_encrypts_sensitive_free_text() -> None:
    assert isinstance(ContactAIMemory.__table__.c.summary.type, EncryptedString)
    assert isinstance(ContactAIMemoryFact.__table__.c.value.type, EncryptedString)
    assert "value_hash" not in ContactAIMemoryFact.__table__.c


def test_contact_ai_memory_is_unique_and_workspace_scoped() -> None:
    memory_table = ContactAIMemory.__table__
    facts_table = ContactAIMemoryFact.__table__

    unique = next(
        constraint
        for constraint in memory_table.constraints
        if constraint.name == "uq_contact_ai_memories_workspace_contact"
    )
    assert isinstance(unique, sa.UniqueConstraint)
    assert [column.name for column in unique.columns] == ["workspace_id", "contact_id"]

    scoped_fk = next(
        constraint
        for constraint in facts_table.constraints
        if constraint.name == "fk_contact_ai_memory_facts_scoped_memory"
    )
    assert isinstance(scoped_fk, sa.ForeignKeyConstraint)
    assert [column.name for column in scoped_fk.columns] == [
        "memory_id",
        "workspace_id",
        "contact_id",
    ]
    assert scoped_fk.ondelete == "CASCADE"


def test_contact_ai_memory_fact_has_lifecycle_and_provenance_columns() -> None:
    columns = ContactAIMemoryFact.__table__.c

    for column_name in (
        "fact_type",
        "value",
        "confidence",
        "provenance_event_id",
        "provenance_message_id",
        "observed_at",
        "expires_at",
        "supersession_state",
        "superseded_at",
        "superseded_by_id",
    ):
        assert column_name in columns

    message_fk = next(iter(columns.provenance_message_id.foreign_keys))
    superseded_by_fk = next(iter(columns.superseded_by_id.foreign_keys))
    assert message_fk.ondelete == "SET NULL"
    assert superseded_by_fk.ondelete == "SET NULL"

    check_names = {
        constraint.name
        for constraint in ContactAIMemoryFact.__table__.constraints
        if isinstance(constraint, sa.CheckConstraint)
    }
    assert {
        "ck_contact_ai_memory_facts_confidence",
        "ck_contact_ai_memory_facts_expiry",
        "ck_contact_ai_memory_facts_supersession_state",
    } <= check_names
