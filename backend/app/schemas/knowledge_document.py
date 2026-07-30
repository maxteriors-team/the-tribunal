"""KnowledgeDocument schemas for CAG knowledge base."""

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeDocumentResponse(BaseModel):
    """Response schema for a single knowledge document."""

    id: uuid.UUID
    workspace_id: uuid.UUID
    agent_id: uuid.UUID | None
    title: str
    doc_type: str
    content: str
    token_count: int
    priority: int
    is_active: bool
    metadata_: dict[str, Any] | None = Field(None, alias="metadata_")
    created_at: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True)


class KnowledgeDocumentCreate(BaseModel):
    """Create schema for a knowledge document."""

    title: str
    content: str
    doc_type: str = "general"
    priority: int = 0
    is_active: bool = True
    metadata_: dict[str, Any] | None = Field(None, alias="metadata_")


class KnowledgeDocumentUpdate(BaseModel):
    """Update schema for a knowledge document."""

    title: str | None = None
    content: str | None = None
    doc_type: str | None = None
    priority: int | None = None
    is_active: bool | None = None
    metadata_: dict[str, Any] | None = Field(None, alias="metadata_")


class KnowledgeDocumentListResponse(BaseModel):
    """Paginated knowledge document list with token info."""

    items: list[KnowledgeDocumentResponse]
    total: int
    total_tokens: int
    token_budget: int
