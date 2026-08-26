"""Model contracts for nullable external conversation provenance."""

import sqlalchemy as sa

from app.models.conversation import Conversation, Message


def test_conversation_source_provider_is_nullable() -> None:
    column = Conversation.__table__.c.source_provider

    assert isinstance(column.type, sa.String)
    assert column.type.length == 50
    assert column.nullable is True
    assert column.server_default is None


def test_message_source_provenance_is_nullable() -> None:
    columns = Message.__table__.c

    assert isinstance(columns.source_provider.type, sa.String)
    assert columns.source_provider.type.length == 50
    assert columns.source_provider.nullable is True
    assert isinstance(columns.external_url.type, sa.String)
    assert columns.external_url.type.length == 2048
    assert columns.external_url.nullable is True
    assert columns.source_provider.server_default is None
    assert columns.external_url.server_default is None
