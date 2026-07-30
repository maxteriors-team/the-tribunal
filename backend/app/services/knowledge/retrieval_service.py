"""Hybrid knowledge retrieval — Python port of noledge ``src/lib/ai/rag``.

Mirrors ``retrieve.ts`` + ``mmr.ts``:

1. Embed the query, then over-fetch candidates from two arms:
   * **vector** — pgvector cosine KNN over ``knowledge_chunks.embedding``.
   * **keyword** — Postgres ``tsvector``/``ts_rank`` full-text search.
2. **Min-max normalize** each arm's raw scores into ``[0, 1]``.
3. **Weighted fusion** of the two normalized arms (default vector 0.7 /
   keyword 0.3, renormalized to sum 1).
4. Drop anything below a **minScore** floor (default 0.3).
5. **MMR** diversity rerank (token-Jaccard similarity, lambda 0.7) to avoid
   near-duplicate chunks crowding the top-k.
6. A pluggable **reranker** seam runs last (identity no-op by default).

Every query is scoped to one ``workspace_id`` and either one ``agent_id`` or
workspace-level documents (``agent_id IS NULL``), so one tenant can never read
another's knowledge base.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace

import structlog
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.models.knowledge_chunk import KnowledgeChunk
from app.models.knowledge_document import KnowledgeDocument
from app.services.ai.embeddings import Embedder, embed_texts

logger = structlog.get_logger()

# ── Defaults (mirror noledge retrieve.ts) ───────────────────────────────────
DEFAULT_TOP_K = 5
DEFAULT_MIN_SCORE = 0.3
DEFAULT_VECTOR_WEIGHT = 0.7
DEFAULT_KEYWORD_WEIGHT = 0.3
DEFAULT_MMR_LAMBDA = 0.7
# Postgres text-search config used by the generated tsvector column + queries.
TS_CONFIG = "english"

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


# ── Reranker seam (port of rerank.ts) ───────────────────────────────────────
# A reranker reorders (and may trim) retrieved chunks for a query, e.g. with a
# cross-encoder or hosted relevance API. It runs after fusion + MMR. Defaults to
# the identity no-op so no network dependency is added.
Reranker = Callable[[str, list["RetrievedChunk"]], Awaitable[list["RetrievedChunk"]]]


async def identity_reranker(_query: str, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """Default reranker: return chunks untouched."""
    return chunks


@dataclass(slots=True)
class Candidate:
    """A chunk surfaced by one or both arms, with normalized per-arm scores."""

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    content: str
    ordinal: int
    char_start: int
    char_end: int
    # Best cosine distance from the vector arm (0 = identical). ``inf`` when the
    # chunk surfaced only via the keyword arm.
    distance: float = float("inf")
    # Per-arm scores AFTER min-max normalization, both in ``[0, 1]``.
    vector_score: float = 0.0
    keyword_score: float = 0.0


@dataclass(slots=True)
class RetrievedChunk:
    """A fused, ranked retrieval result."""

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    content: str
    ordinal: int
    char_start: int
    char_end: int
    distance: float
    # Combined normalized relevance score in ``[0, 1]`` (higher = better).
    score: float


@dataclass(slots=True)
class RetrievedPassage:
    """A ranked retrieval result enriched with its source document title.

    This is the citation-friendly shape returned to the on-demand
    ``search_knowledge`` tool: the model gets the passage text plus the human
    title of the document it came from so it can attribute facts out loud.
    """

    document_id: uuid.UUID
    title: str
    content: str
    score: float
    ordinal: int


@dataclass(slots=True)
class ScoredCandidate:
    """A candidate paired with its fused score (intermediate fusion output)."""

    candidate: Candidate
    score: float


@dataclass(slots=True)
class RetrieveOptions:
    """Knobs mirroring noledge ``RetrieveOptions`` (subset that applies here)."""

    top_k: int = DEFAULT_TOP_K
    min_score: float = DEFAULT_MIN_SCORE
    vector_weight: float = DEFAULT_VECTOR_WEIGHT
    keyword_weight: float = DEFAULT_KEYWORD_WEIGHT
    hybrid: bool = True
    use_mmr: bool = True
    mmr_lambda: float = DEFAULT_MMR_LAMBDA
    embedder: Embedder | None = None
    reranker: Reranker | None = None
    # Back-compat: max cosine distance for the vector arm. When set, overrides
    # ``min_score`` with ``1 - max_distance`` (matches noledge ``maxDistance``).
    max_distance: float | None = None


# ── Pure helpers ────────────────────────────────────────────────────────────
def clamp01(value: float) -> float:
    """Clamp ``value`` into ``[0, 1]``."""
    if value < 0:
        return 0.0
    if value > 1:
        return 1.0
    return value


def candidate_count(top_k: int) -> int:
    """Per-arm over-fetch so filtering/MMR never under-fills ``top_k``."""
    return max(top_k * 3, top_k + 8)


def min_max_normalize(values: list[float]) -> list[float]:
    """Min-max scale ``values`` into ``[0, 1]``.

    A zero span (all equal, or a single element) maps every entry to ``1.0``,
    matching noledge's ``span === 0 ? 1`` keyword-arm behavior.
    """
    if not values:
        return []
    lo = min(values)
    hi = max(values)
    span = hi - lo
    if span == 0:
        return [1.0 for _ in values]
    return [(value - lo) / span for value in values]


def normalize_weights(vector_weight: float, keyword_weight: float) -> tuple[float, float]:
    """Clamp negatives to 0 and renormalize the two weights to sum to 1.

    If both are zero, fall back to a pure-vector ``(1, 0)`` split (mirrors the
    reference clamp logic: ``weightSum === 0 ? 1 : ...``).
    """
    v = max(0.0, vector_weight)
    k = max(0.0, keyword_weight)
    total = v + k
    if total == 0:
        return 1.0, 0.0
    return v / total, k / total


def tokenize(text: str) -> set[str]:
    """Lowercase word/number tokens of ``text`` as a set (for Jaccard)."""
    return set(_TOKEN_PATTERN.findall(text.lower()))


def jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard similarity ``|a ∩ b| / |a ∪ b|`` in ``[0, 1]``; empty/empty → 0."""
    if not a and not b:
        return 0.0
    intersection = len(a & b)
    union = len(a) + len(b) - intersection
    return 0.0 if union == 0 else intersection / union


def compute_mmr(relevance: float, max_sim: float, lambda_: float) -> float:
    """MMR objective for one candidate: ``λ·relevance − (1−λ)·maxSim``."""
    return lambda_ * relevance - (1 - lambda_) * max_sim


def mmr_rerank(
    items: list[ScoredCandidate],
    lambda_: float = DEFAULT_MMR_LAMBDA,
    limit: int | None = None,
) -> list[ScoredCandidate]:
    """Greedy MMR rerank (token-Jaccard similarity). Pure and deterministic.

    Input order is the tie-breaker, so passing items pre-sorted by score keeps
    results stable. Port of noledge ``mmrRerank``.
    """
    cap = len(items) if limit is None else limit
    if not items or cap <= 0:
        return []

    tokens = [tokenize(item.candidate.content) for item in items]
    remaining = list(range(len(items)))
    selected: list[int] = []

    while len(selected) < cap and remaining:
        best_pos = 0
        best_value = float("-inf")
        for pos, index in enumerate(remaining):
            max_sim = 0.0
            for chosen in selected:
                sim = jaccard(tokens[index], tokens[chosen])
                max_sim = max(max_sim, sim)
            value = compute_mmr(items[index].score, max_sim, lambda_)
            if value > best_value:
                best_value = value
                best_pos = pos
        selected.append(remaining.pop(best_pos))

    return [items[index] for index in selected]


def fuse_and_filter(
    candidates: list[Candidate],
    vector_weight: float,
    keyword_weight: float,
    min_score: float,
) -> list[ScoredCandidate]:
    """Weighted-fuse the two normalized arms, drop sub-floor, sort by score.

    Weights are renormalized to sum to 1 first. Mirrors the fusion block of
    noledge ``retrieveChunks``.
    """
    v_weight, k_weight = normalize_weights(vector_weight, keyword_weight)
    scored = [
        ScoredCandidate(
            candidate=candidate,
            score=v_weight * candidate.vector_score + k_weight * candidate.keyword_score,
        )
        for candidate in candidates
    ]
    survivors = [entry for entry in scored if entry.score >= min_score]
    survivors.sort(key=lambda entry: entry.score, reverse=True)
    return survivors


# ── DB query builders (workspace + optional agent scoped) ───────────────────
def _chunk_agent_scope(agent_id: uuid.UUID | None) -> ColumnElement[bool]:
    """Match one agent, or only workspace-level chunks when no agent is supplied."""

    if agent_id is None:
        return KnowledgeChunk.agent_id.is_(None)
    return KnowledgeChunk.agent_id == agent_id


def _build_vector_stmt(
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID | None,
    query_vector: list[float],
    limit: int,
) -> Select[tuple[uuid.UUID, uuid.UUID, str, int, int, int, float]]:
    """KNN over-fetch ordered by cosine distance, scoped to workspace + agent."""
    distance = KnowledgeChunk.embedding.cosine_distance(query_vector).label("distance")
    return (
        select(
            KnowledgeChunk.id,
            KnowledgeChunk.document_id,
            KnowledgeChunk.content,
            KnowledgeChunk.ordinal,
            KnowledgeChunk.char_start,
            KnowledgeChunk.char_end,
            distance,
        )
        .where(
            KnowledgeChunk.workspace_id == workspace_id,
            _chunk_agent_scope(agent_id),
        )
        .order_by(distance.asc())
        .limit(limit)
    )


def _build_keyword_stmt(
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID | None,
    query: str,
    limit: int,
) -> Select[tuple[uuid.UUID, uuid.UUID, str, int, int, int, float]]:
    """Full-text over-fetch ranked by ts_rank, scoped to workspace + agent."""
    ts_query = func.websearch_to_tsquery(TS_CONFIG, query)
    rank = func.ts_rank(KnowledgeChunk.search_vector, ts_query).label("rank")
    return (
        select(
            KnowledgeChunk.id,
            KnowledgeChunk.document_id,
            KnowledgeChunk.content,
            KnowledgeChunk.ordinal,
            KnowledgeChunk.char_start,
            KnowledgeChunk.char_end,
            rank,
        )
        .where(
            KnowledgeChunk.workspace_id == workspace_id,
            _chunk_agent_scope(agent_id),
            KnowledgeChunk.search_vector.op("@@")(ts_query),
        )
        .order_by(rank.desc())
        .limit(limit)
    )


class KnowledgeRetrievalService:
    """Hybrid vector + keyword retrieval over ``knowledge_chunks``."""

    async def retrieve(
        self,
        db: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        agent_id: uuid.UUID | None,
        query: str,
        options: RetrieveOptions | None = None,
    ) -> list[RetrievedChunk]:
        """Return the top-k most relevant chunks for ``query``.

        Over-fetch per arm → min-max normalize each arm → weighted fuse → filter
        by ``min_score`` → MMR diversify → slice to ``top_k`` → rerank. Always
        scoped to ``workspace_id`` plus one agent, or workspace-level documents
        when ``agent_id`` is ``None``.
        """
        opts = options or RetrieveOptions()
        embedder = opts.embedder or embed_texts
        reranker = opts.reranker or identity_reranker

        min_score = (
            clamp01(1 - opts.max_distance) if opts.max_distance is not None else opts.min_score
        )

        trimmed = query.strip()
        if not trimmed:
            return []

        embedded = await embedder([trimmed])
        if not embedded.ok or not embedded.embeddings:
            logger.warning(
                "knowledge_retrieval_embed_failed",
                workspace_id=str(workspace_id),
                agent_id=str(agent_id) if agent_id is not None else None,
                error=embedded.error,
            )
            return []
        query_vector = embedded.embeddings[0]

        candidate_k = candidate_count(opts.top_k)
        candidates: dict[uuid.UUID, Candidate] = {}

        # ── Vector arm ──────────────────────────────────────────────────────
        vector_rows = (
            await db.execute(_build_vector_stmt(workspace_id, agent_id, query_vector, candidate_k))
        ).all()
        raw_vector_scores = [1.0 - float(row.distance) for row in vector_rows]
        norm_vector_scores = min_max_normalize(raw_vector_scores)
        for row, v_score in zip(vector_rows, norm_vector_scores, strict=True):
            candidates[row.id] = Candidate(
                chunk_id=row.id,
                document_id=row.document_id,
                content=row.content,
                ordinal=row.ordinal,
                char_start=row.char_start,
                char_end=row.char_end,
                distance=float(row.distance),
                vector_score=v_score,
                keyword_score=0.0,
            )

        # ── Keyword arm ─────────────────────────────────────────────────────
        if opts.hybrid:
            keyword_rows = (
                await db.execute(_build_keyword_stmt(workspace_id, agent_id, trimmed, candidate_k))
            ).all()
            raw_keyword_scores = [float(row.rank) for row in keyword_rows]
            norm_keyword_scores = min_max_normalize(raw_keyword_scores)
            for row, k_score in zip(keyword_rows, norm_keyword_scores, strict=True):
                existing = candidates.get(row.id)
                if existing is not None:
                    existing.keyword_score = k_score
                    continue
                candidates[row.id] = Candidate(
                    chunk_id=row.id,
                    document_id=row.document_id,
                    content=row.content,
                    ordinal=row.ordinal,
                    char_start=row.char_start,
                    char_end=row.char_end,
                    distance=float("inf"),
                    vector_score=0.0,
                    keyword_score=k_score,
                )

        # ── Fuse → filter → MMR → slice ─────────────────────────────────────
        scored = fuse_and_filter(
            list(candidates.values()),
            opts.vector_weight,
            opts.keyword_weight,
            min_score,
        )
        selected = (
            mmr_rerank(scored, lambda_=opts.mmr_lambda, limit=opts.top_k)
            if opts.use_mmr
            else scored[: opts.top_k]
        )

        chunks = [
            RetrievedChunk(
                chunk_id=entry.candidate.chunk_id,
                document_id=entry.candidate.document_id,
                content=entry.candidate.content,
                ordinal=entry.candidate.ordinal,
                char_start=entry.candidate.char_start,
                char_end=entry.candidate.char_end,
                distance=entry.candidate.distance,
                score=entry.score,
            )
            for entry in selected
        ]
        return await reranker(trimmed, chunks)

    async def retrieve_passages(
        self,
        db: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        agent_id: uuid.UUID | None,
        query: str,
        top_k: int | None = None,
        options: RetrieveOptions | None = None,
    ) -> list[RetrievedPassage]:
        """Retrieve the top-k chunks and enrich them with document titles.

        Thin wrapper over :meth:`retrieve` for the on-demand ``search_knowledge``
        tool: runs the hybrid pipeline (scoped to ``workspace_id`` plus one agent,
        or to workspace-level documents when ``agent_id`` is ``None``), then
        resolves each surviving chunk's parent document title in a single query
        so the model can cite sources. Order is preserved.
        """
        opts = options or RetrieveOptions()
        if top_k is not None:
            opts = replace(opts, top_k=top_k)

        chunks = await self.retrieve(
            db,
            workspace_id=workspace_id,
            agent_id=agent_id,
            query=query,
            options=opts,
        )
        if not chunks:
            return []

        document_ids = {chunk.document_id for chunk in chunks}
        document_agent_scope = (
            KnowledgeDocument.agent_id.is_(None)
            if agent_id is None
            else KnowledgeDocument.agent_id == agent_id
        )

        title_rows = (
            await db.execute(
                select(KnowledgeDocument.id, KnowledgeDocument.title).where(
                    KnowledgeDocument.id.in_(document_ids),
                    KnowledgeDocument.workspace_id == workspace_id,
                    document_agent_scope,
                )
            )
        ).all()
        titles = {row.id: row.title for row in title_rows}

        return [
            RetrievedPassage(
                document_id=chunk.document_id,
                title=titles.get(chunk.document_id, "Untitled"),
                content=chunk.content,
                score=chunk.score,
                ordinal=chunk.ordinal,
            )
            for chunk in chunks
        ]


knowledge_retrieval_service = KnowledgeRetrievalService()
