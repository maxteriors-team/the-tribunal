"""Conversation note input validation.

Deliberately DB-free. The behavioural tests for notes live in
``tests/integration/test_conversation_notes.py``, which is marked ``integration``
and therefore excluded from the default suite CI runs, so the boundary rules
that keep junk out of an encrypted column are asserted here too.
"""

import pytest
from pydantic import ValidationError

from app.models.conversation_note import MAX_NOTE_BODY_CHARS
from app.schemas.conversation_note import ConversationNoteCreate, ConversationNoteUpdate

SCHEMAS = (ConversationNoteCreate, ConversationNoteUpdate)


@pytest.mark.parametrize("schema", SCHEMAS)
@pytest.mark.parametrize("body", ["", "   ", "\n\t ", "\u3000"])
def test_blank_notes_are_rejected(schema: type, body: str) -> None:
    """An empty note is indistinguishable from a lost one in the timeline."""
    with pytest.raises(ValidationError):
        schema(body=body)


@pytest.mark.parametrize("schema", SCHEMAS)
def test_surrounding_whitespace_is_stripped(schema: type) -> None:
    assert schema(body="  Steep gable, two storey  ").body == "Steep gable, two storey"


@pytest.mark.parametrize("schema", SCHEMAS)
def test_oversized_notes_are_rejected(schema: type) -> None:
    """The cap is enforced on readable text, before anything is encrypted.

    The database also bounds the column, but that bound is on ciphertext, so
    this is where a human-meaningful limit can actually be applied.
    """
    with pytest.raises(ValidationError):
        schema(body="x" * (MAX_NOTE_BODY_CHARS + 1))


@pytest.mark.parametrize("schema", SCHEMAS)
def test_a_note_at_the_limit_is_accepted(schema: type) -> None:
    assert len(schema(body="x" * MAX_NOTE_BODY_CHARS).body) == MAX_NOTE_BODY_CHARS
