"""Knowledge document management endpoints for CAG system."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DB, CurrentUser, get_workspace, require_route_capabilities
from app.core.permissions import Capability
from app.db.pagination import paginate
from app.models.agent import Agent
from app.models.knowledge_document import KnowledgeDocument
from app.models.workspace import Workspace
from app.schemas.knowledge_document import (
    KnowledgeDocumentCreate,
    KnowledgeDocumentListResponse,
    KnowledgeDocumentResponse,
    KnowledgeDocumentUpdate,
)
from app.services.ai.embeddings import Embedder, create_workspace_embedder
from app.services.automations.events import (
    EVENT_KNOWLEDGE_DOCUMENT_UPLOADED,
    emit_automation_event,
)
from app.services.knowledge.ingestion_service import (
    IngestionError,
    knowledge_ingestion_service,
)
from app.services.knowledge.knowledge_context_service import knowledge_context_service

router = APIRouter(
    dependencies=[
        Depends(require_route_capabilities(Capability.CRM_READ, Capability.WORKSPACE_MANAGE))
    ]
)


async def _reindex_or_400(db: AsyncSession, doc: KnowledgeDocument, *, embedder: Embedder) -> None:
    """Chunk + embed ``doc`` inside the caller's transaction (no commit here).

    Embedding failures surface as a 502 so the caller's transaction rolls back
    and the document is never persisted half-indexed.
    """
    try:
        await knowledge_ingestion_service.reindex_document(db, doc, embedder=embedder)
    except IngestionError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to index knowledge document embeddings.",
        ) from exc


def _doc_to_response(doc: KnowledgeDocument) -> KnowledgeDocumentResponse:
    """Convert a KnowledgeDocument model to a KnowledgeDocumentResponse."""
    return KnowledgeDocumentResponse(
        id=doc.id,
        workspace_id=doc.workspace_id,
        agent_id=doc.agent_id,
        title=doc.title,
        doc_type=doc.doc_type,
        content=doc.content,
        token_count=doc.token_count,
        priority=doc.priority,
        is_active=doc.is_active,
        metadata_=doc.metadata_,
        created_at=doc.created_at.isoformat(),
        updated_at=doc.updated_at.isoformat(),
    )


async def _get_agent_or_404(
    db: AsyncSession,
    agent_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> Agent:
    """Verify agent exists and belongs to workspace."""
    result = await db.execute(
        select(Agent).where(
            Agent.id == agent_id,
            Agent.workspace_id == workspace_id,
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found",
        )
    return agent


@router.get("", response_model=KnowledgeDocumentListResponse)
async def list_documents(
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> KnowledgeDocumentListResponse:
    """List knowledge documents for an agent with token budget info."""
    await _get_agent_or_404(db, agent_id, workspace_id)

    query = (
        select(KnowledgeDocument)
        .where(
            KnowledgeDocument.agent_id == agent_id,
            KnowledgeDocument.workspace_id == workspace_id,
        )
        .order_by(
            KnowledgeDocument.priority.desc(),
            KnowledgeDocument.created_at.asc(),
        )
    )

    result = await paginate(db, query, page=page, page_size=page_size)
    total_tokens = await knowledge_context_service.get_total_tokens(db, agent_id)

    return KnowledgeDocumentListResponse(
        items=[_doc_to_response(doc) for doc in result.items],
        total=result.total,
        total_tokens=total_tokens,
        token_budget=knowledge_context_service.TOKEN_BUDGET_DEFAULT,
    )


@router.post(
    "",
    response_model=KnowledgeDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_document(
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    body: KnowledgeDocumentCreate,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> KnowledgeDocumentResponse:
    """Create a new knowledge document for an agent."""
    await _get_agent_or_404(db, agent_id, workspace_id)
    # Resolve credentials before adding the document because OAuth refresh may commit.
    embedder = await create_workspace_embedder(db, workspace_id)

    token_count = knowledge_context_service.count_tokens(body.content)

    doc = KnowledgeDocument(
        workspace_id=workspace_id,
        agent_id=agent_id,
        title=body.title,
        content=body.content,
        doc_type=body.doc_type,
        priority=body.priority,
        is_active=body.is_active,
        metadata_=body.metadata_ or {},
        token_count=token_count,
    )
    db.add(doc)
    # Flush so the document gets its id before chunks reference it; both the
    # document and its chunks/embeddings then commit in one transaction.
    await db.flush()
    await _reindex_or_400(db, doc, embedder=embedder)
    await emit_automation_event(
        db,
        workspace_id=workspace_id,
        event_type=EVENT_KNOWLEDGE_DOCUMENT_UPLOADED,
        contact_id=None,
        payload={
            "document_id": str(doc.id),
            "agent_id": str(agent_id),
            "title": doc.title,
            "doc_type": doc.doc_type,
        },
    )
    await db.commit()
    await db.refresh(doc)

    return _doc_to_response(doc)


@router.get("/{doc_id}", response_model=KnowledgeDocumentResponse)
async def get_document(
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    doc_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> KnowledgeDocumentResponse:
    """Get a specific knowledge document."""
    await _get_agent_or_404(db, agent_id, workspace_id)

    result = await db.execute(
        select(KnowledgeDocument).where(
            KnowledgeDocument.id == doc_id,
            KnowledgeDocument.agent_id == agent_id,
            KnowledgeDocument.workspace_id == workspace_id,
        )
    )
    doc = result.scalar_one_or_none()

    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge document not found",
        )

    return _doc_to_response(doc)


@router.patch("/{doc_id}", response_model=KnowledgeDocumentResponse)
async def update_document(
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    doc_id: uuid.UUID,
    body: KnowledgeDocumentUpdate,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> KnowledgeDocumentResponse:
    """Update a knowledge document. Recomputes token_count if content changes."""
    await _get_agent_or_404(db, agent_id, workspace_id)

    result = await db.execute(
        select(KnowledgeDocument).where(
            KnowledgeDocument.id == doc_id,
            KnowledgeDocument.agent_id == agent_id,
            KnowledgeDocument.workspace_id == workspace_id,
        )
    )
    doc = result.scalar_one_or_none()

    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge document not found",
        )

    update_data = body.model_dump(exclude_unset=True)
    embedder = (
        await create_workspace_embedder(db, workspace_id) if "content" in update_data else None
    )
    for field, value in update_data.items():
        setattr(doc, field, value)

    # Recompute token_count and re-index chunks/embeddings if content changed.
    if embedder is not None:
        doc.token_count = knowledge_context_service.count_tokens(doc.content)
        await db.flush()
        await _reindex_or_400(db, doc, embedder=embedder)

    await db.commit()
    await db.refresh(doc)

    return _doc_to_response(doc)


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    doc_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> None:
    """Delete a knowledge document."""
    await _get_agent_or_404(db, agent_id, workspace_id)

    result = await db.execute(
        select(KnowledgeDocument).where(
            KnowledgeDocument.id == doc_id,
            KnowledgeDocument.agent_id == agent_id,
            KnowledgeDocument.workspace_id == workspace_id,
        )
    )
    doc = result.scalar_one_or_none()

    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge document not found",
        )

    await db.delete(doc)
    await db.commit()
