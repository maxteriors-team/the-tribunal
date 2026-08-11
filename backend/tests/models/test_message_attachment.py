"""Model contract tests for durable inbound message attachments."""

import sqlalchemy as sa

from app.core.encryption import EncryptedString
from app.models.message_attachment import (
    MESSAGE_ATTACHMENT_FAILED,
    MESSAGE_ATTACHMENT_PENDING,
    MESSAGE_ATTACHMENT_PROCESSING,
    MESSAGE_ATTACHMENT_READY,
    MessageAttachment,
)


def test_message_attachment_encrypts_provider_url_and_scopes_workspace() -> None:
    table = MessageAttachment.__table__

    assert isinstance(table.c.source_url.type, EncryptedString)
    assert table.c.workspace_id.nullable is False
    assert table.c.message_id.nullable is False
    assert table.c.storage_key.nullable is True
    assert table.c.status.server_default is not None
    assert table.c.status.server_default.arg == MESSAGE_ATTACHMENT_PENDING


def test_message_attachment_foreign_keys_cascade() -> None:
    table = MessageAttachment.__table__
    workspace_foreign_key = next(iter(table.c.workspace_id.foreign_keys))
    message_foreign_key = next(iter(table.c.message_id.foreign_keys))

    assert workspace_foreign_key.target_fullname == "workspaces.id"
    assert workspace_foreign_key.ondelete == "CASCADE"
    assert message_foreign_key.target_fullname == "messages.id"
    assert message_foreign_key.ondelete == "CASCADE"


def test_message_attachment_queue_constraints_and_indexes_are_declared() -> None:
    table = MessageAttachment.__table__
    constraint_names = {constraint.name for constraint in table.constraints}
    index_names = {index.name for index in table.indexes}

    assert "ck_message_attachments_status" in constraint_names
    assert "ck_message_attachments_provider_position_nonnegative" in constraint_names
    assert "ck_message_attachments_attempt_count_nonnegative" in constraint_names
    assert "uq_message_attachments_message_position" in constraint_names
    assert "uq_message_attachments_storage_key" in constraint_names
    assert "ix_message_attachments_queue" in index_names
    assert "ix_message_attachments_workspace_id" in index_names
    assert "ix_message_attachments_message_id" in index_names

    message_position = next(
        constraint
        for constraint in table.constraints
        if constraint.name == "uq_message_attachments_message_position"
    )
    assert isinstance(message_position, sa.UniqueConstraint)
    assert [column.name for column in message_position.columns] == [
        "message_id",
        "provider_position",
    ]


def test_message_attachment_status_values_are_stable() -> None:
    assert {
        MESSAGE_ATTACHMENT_PENDING,
        MESSAGE_ATTACHMENT_PROCESSING,
        MESSAGE_ATTACHMENT_READY,
        MESSAGE_ATTACHMENT_FAILED,
    } == {"pending", "processing", "ready", "failed"}
