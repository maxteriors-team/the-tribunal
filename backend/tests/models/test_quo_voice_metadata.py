"""Model contract for Quo voicemail timeline metadata."""

import sqlalchemy as sa

from app.models.conversation import Message


def test_message_voicemail_indicator_is_expand_only() -> None:
    column = Message.__table__.c.is_voicemail

    assert isinstance(column.type, sa.Boolean)
    assert column.nullable is True
    assert column.default is not None
    assert column.server_default is not None
