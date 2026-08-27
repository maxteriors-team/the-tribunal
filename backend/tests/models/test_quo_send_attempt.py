"""Schema invariants for durable Quo send attempts."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint

from app.models.quo_send_attempt import QuoSendAttempt


def test_quo_send_attempt_has_database_owned_identity_and_no_message_pii() -> None:
    table = QuoSendAttempt.__table__

    assert {column.name for column in table.columns} == {
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
    assert "body" not in table.columns
    assert "phone_number" not in table.columns

    foreign_targets = {
        tuple(element.target_fullname for element in constraint.elements)
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }
    assert foreign_targets == {
        ("workspaces.id",),
        ("conversations.id",),
        ("messages.id",),
    }
    unique_names = {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert unique_names == {
        "uq_quo_send_attempts_workspace_request",
        "uq_quo_send_attempts_message",
    }
    checks = [
        constraint for constraint in table.constraints if isinstance(constraint, CheckConstraint)
    ]
    assert len(checks) == 1
    assert "unknown" in str(checks[0].sqltext)
