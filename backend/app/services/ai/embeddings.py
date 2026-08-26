"""Embedding helpers for the knowledge retrieval pipeline.

Wraps the OpenAI ``text-embedding-3-small`` model (1536 dimensions) behind a
small, pluggable :class:`Embedder` protocol so the retrieval service can be
exercised in tests with a deterministic fake embedder and no network access.

This mirrors the ``embedTexts`` seam in noledge (``src/lib/ai/embeddings``):
callers pass a batch of texts and receive a result object that is either a list
of vectors or an error string, so retrieval can stay resilient instead of
throwing on a transient embedding failure.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Protocol, cast, runtime_checkable

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai.openai_credentials import (
    create_openai_client,
    create_workspace_openai_client,
)

logger = structlog.get_logger()

# OpenAI embedding model + its fixed output dimensionality. The
# ``knowledge_chunks.embedding`` column is declared ``vector(1536)``, so this
# constant and the migration/model must stay in lockstep.
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536


@dataclass(frozen=True, slots=True)
class EmbeddingResult:
    """Result of an embedding call.

    ``ok`` discriminates the two arms: on success ``embeddings`` holds one vector
    per input text (order preserved); on failure ``error`` carries a short,
    log-safe message. Modeled after noledge's ``Result`` so retrieval callers can
    branch without exception handling on the hot path.
    """

    ok: bool
    embeddings: list[list[float]] | None = None
    error: str | None = None


@runtime_checkable
class Embedder(Protocol):
    """Callable that turns a batch of texts into embedding vectors.

    The retrieval service depends only on this protocol, so tests can inject a
    deterministic stub and production can use :func:`embed_texts`.
    """

    async def __call__(self, texts: list[str]) -> EmbeddingResult: ...


async def _embed_with_client(client: Any, texts: list[str]) -> EmbeddingResult:
    """Embed one batch with an already-authorized OpenAI client."""
    if not texts:
        return EmbeddingResult(ok=True, embeddings=[])

    try:
        response = await client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=texts,
            dimensions=EMBEDDING_DIM,
        )
    except Exception as exc:  # noqa: BLE001 - degrade gracefully, never leak SDK errors
        logger.warning("embedding_request_failed", error_type=type(exc).__name__)
        return EmbeddingResult(ok=False, error="Embedding request failed.")

    # The SDK returns items in arbitrary order; sort by ``index`` to realign with
    # the input batch before stripping to plain float lists.
    ordered = sorted(response.data, key=lambda item: item.index)
    vectors = [list(item.embedding) for item in ordered]
    return EmbeddingResult(ok=True, embeddings=vectors)


async def embed_texts(texts: list[str]) -> EmbeddingResult:
    """Embed with the global OpenAI credential for non-workspace callers."""
    try:
        client = create_openai_client()
    except Exception as exc:  # noqa: BLE001 - return the same log-safe failure contract
        logger.warning("embedding_client_creation_failed", error_type=type(exc).__name__)
        return EmbeddingResult(ok=False, error="Embedding request failed.")
    return await _embed_with_client(client, texts)


async def create_workspace_embedder(db: AsyncSession, workspace_id: uuid.UUID) -> Embedder:
    """Resolve one workspace-scoped client before its caller mutates the session."""
    try:
        client = await create_workspace_openai_client(db, workspace_id)
    except Exception as exc:  # noqa: BLE001 - never expose credential resolution details
        logger.warning(
            "embedding_client_creation_failed",
            workspace_id=str(workspace_id),
            error_type=type(exc).__name__,
        )

        async def failed_embedder(_texts: list[str]) -> EmbeddingResult:
            return EmbeddingResult(ok=False, error="Embedding request failed.")

        return cast(Embedder, failed_embedder)

    async def embed(texts: list[str]) -> EmbeddingResult:
        return await _embed_with_client(client, texts)

    return embed


async def embed_query(text: str) -> list[float] | None:
    """Embed a single query string, returning ``None`` on empty input or failure."""
    trimmed = text.strip()
    if not trimmed:
        return None
    result = await embed_texts([trimmed])
    if not result.ok or not result.embeddings:
        return None
    return result.embeddings[0]
