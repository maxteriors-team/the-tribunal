"""Schemas for conversation notes."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.conversation_note import MAX_NOTE_BODY_CHARS


def _require_content(value: str) -> str:
    """Reject whitespace-only notes, which read as data loss in the timeline."""
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("Note body cannot be empty")
    return cleaned


class ConversationNoteCreate(BaseModel):
    """A note a rep is adding to a conversation."""

    body: str = Field(..., min_length=1, max_length=MAX_NOTE_BODY_CHARS)

    _strip_body = field_validator("body")(_require_content)


class ConversationNoteUpdate(BaseModel):
    """An edit to a note the caller authored."""

    body: str = Field(..., min_length=1, max_length=MAX_NOTE_BODY_CHARS)

    _strip_body = field_validator("body")(_require_content)


class ConversationNoteResponse(BaseModel):
    """A note as rendered in the conversation's notes rail."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID
    body: str
    # "human" or "quo_summary"; the UI badges synced summaries so a rep never
    # mistakes an AI recap for a colleague's observation.
    source: str
    author_user_id: int | None = None
    author_name: str | None = None
    created_at: datetime
    updated_at: datetime
