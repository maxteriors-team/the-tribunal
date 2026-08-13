"""Bundled product-help source used directly by ``search_help``.

Before this existed, product questions had no grounded answer: customer-facing
agent knowledge contains per-tenant business material, not instructions for the
CRM itself. The operator corpus therefore ships as markdown under
``backend/docs/help`` so it is present in backend-only production deploys.

``search_help_documents`` ranks sections from those files at request time. A docs
change becomes authoritative with the deployment and does not depend on a seed
job, an embedding provider, or potentially stale database rows. The optional
``sync_product_help`` path remains for consumers that want the same articles in
the hybrid knowledge index; it is idempotent and skips unchanged chunk hashes.
"""

from __future__ import annotations

import math
import re
import uuid
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.scope import select_workspace_owned
from app.models.knowledge_document import KnowledgeDocument
from app.services.ai.embeddings import Embedder
from app.services.knowledge.ingestion_service import knowledge_ingestion_service
from app.services.knowledge.knowledge_context_service import knowledge_context_service

logger = structlog.get_logger()

# ``doc_type`` marking a document as product help rather than tenant business
# content. Agent-facing knowledge UIs filter by agent, so these never show up
# there, but the type keeps the two corpora separable in queries and exports.
PRODUCT_HELP_DOC_TYPE = "product_help"

# backend/app/services/knowledge/product_help.py -> backend/docs/help
HELP_DOCS_DIR = Path(__file__).resolve().parents[3] / "docs" / "help"


class ProductHelpError(Exception):
    """The bundled help corpus is missing or unreadable."""


@dataclass(frozen=True, slots=True)
class HelpDocument:
    """One markdown help article, ready to persist."""

    slug: str
    title: str
    content: str


@dataclass(frozen=True, slots=True)
class HelpPassage:
    """One ranked section from a bundled product-help article."""

    title: str
    content: str
    source: str
    score: float


@dataclass(frozen=True, slots=True)
class ProductHelpSyncResult:
    """Outcome of syncing the corpus into one workspace."""

    workspace_id: uuid.UUID
    created: int
    updated: int
    indexed: int
    skipped: int

    @property
    def total(self) -> int:
        return self.created + self.updated


def _title_from_markdown(text: str, fallback: str) -> str:
    """Use the document's first ``# `` heading as its title."""

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return fallback


def load_help_documents(directory: Path | None = None) -> list[HelpDocument]:
    """Read every markdown help article, sorted by slug.

    Raises :class:`ProductHelpError` when the corpus directory is missing or
    empty — a silent empty sync would leave ``search_help`` answering "no
    matching help" forever, which reads exactly like a working-but-unhelpful
    tool.
    """

    source = directory or HELP_DOCS_DIR
    if not source.is_dir():
        raise ProductHelpError(f"Help corpus directory not found: {source}")

    documents: list[HelpDocument] = []
    try:
        paths = sorted(source.glob("*.md"))
        for path in paths:
            content = path.read_text(encoding="utf-8").strip()
            if not content:
                continue
            documents.append(
                HelpDocument(
                    slug=path.stem,
                    title=_title_from_markdown(
                        content,
                        path.stem.replace("-", " ").title(),
                    ),
                    content=content,
                )
            )
    except OSError as exc:
        raise ProductHelpError(f"Could not read help corpus at {source}: {exc}") from exc

    if not documents:
        raise ProductHelpError(f"Help corpus directory has no markdown files: {source}")
    return documents


@lru_cache(maxsize=1)
def load_product_help_articles() -> list[HelpDocument]:
    """Load the deployed corpus once per backend process."""

    return load_help_documents()


# Question filler must not make an unrelated article look relevant. Product
# nouns and action verbs intentionally stay searchable.
_SEARCH_STOP_WORDS = frozenset(
    {
        "a",
        "about",
        "an",
        "and",
        "are",
        "can",
        "could",
        "crm",
        "do",
        "does",
        "find",
        "for",
        "from",
        "go",
        "how",
        "i",
        "in",
        "is",
        "it",
        "me",
        "my",
        "of",
        "on",
        "please",
        "see",
        "show",
        "system",
        "tell",
        "that",
        "the",
        "this",
        "to",
        "tribunal",
        "view",
        "want",
        "what",
        "when",
        "where",
        "which",
        "with",
        "would",
        "you",
    }
)

_SEARCH_ALIASES: dict[str, frozenset[str]] = {
    "appointment": frozenset({"appointment", "booking", "calendar", "schedule"}),
    "bill": frozenset({"bill", "invoice"}),
    "billing": frozenset({"billing", "invoice", "subscription"}),
    "call": frozenset({"call", "phone", "voice"}),
    "customer": frozenset({"customer", "contact", "lead"}),
    "estimate": frozenset({"estimate", "quote", "proposal"}),
    "followup": frozenset({"followup", "follow", "nudge"}),
    "lead": frozenset({"lead", "contact", "prospect"}),
    "message": frozenset({"message", "sms", "text", "conversation"}),
    "payment": frozenset({"payment", "paid", "invoice"}),
    "pipeline": frozenset({"pipeline", "opportunity", "stage"}),
    "product": frozenset({"product", "catalog", "item"}),
    "proposal": frozenset({"proposal", "quote", "estimate"}),
    "staff": frozenset({"staff", "team", "member", "role"}),
    "stock": frozenset({"stock", "inventory"}),
    "text": frozenset({"text", "sms", "message", "conversation"}),
}


def _search_tokenize(text: str) -> list[str]:
    """Return stable lowercase terms with conservative plural normalization."""

    terms: list[str] = []
    for raw in re.findall(r"[a-z0-9]+", text.lower()):
        if len(raw) > 4 and raw.endswith("ies"):
            raw = f"{raw[:-3]}y"
        elif len(raw) > 4 and raw.endswith("s") and not raw.endswith("ss"):
            raw = raw[:-1]
        if raw not in _SEARCH_STOP_WORDS and len(raw) > 1:
            terms.append(raw)
    return terms


def _query_concepts(query: str) -> list[frozenset[str]]:
    """Expand common operator wording without making aliases extra requirements."""

    concepts: list[frozenset[str]] = []
    seen: set[frozenset[str]] = set()
    for term in _search_tokenize(query):
        concept = _SEARCH_ALIASES.get(term, frozenset({term}))
        if concept not in seen:
            seen.add(concept)
            concepts.append(concept)
    return concepts


def _preamble_has_guidance(lines: list[str]) -> bool:
    """Return whether pre-heading lines contain guidance beyond metadata and H1."""

    in_frontmatter = False
    for line in lines:
        stripped = line.strip()
        if stripped == "---":
            in_frontmatter = not in_frontmatter
            continue
        if in_frontmatter or not stripped or stripped.startswith("# "):
            continue
        return True
    return False


def _article_sections(document: HelpDocument) -> list[tuple[str, str]]:
    """Split an article at level-two headings while preserving source text."""

    sections: list[tuple[str, list[str]]] = []
    heading = document.title
    lines: list[str] = []
    found_section = False
    for line in document.content.splitlines():
        if line.startswith("## "):
            if (found_section and any(part.strip() for part in lines)) or (
                not found_section and _preamble_has_guidance(lines)
            ):
                sections.append((heading, lines))
            found_section = True
            heading = line[3:].strip()
            lines = [line]
        elif found_section or not sections:
            lines.append(line)
    if found_section and any(part.strip() for part in lines):
        sections.append((heading, lines))

    if not found_section:
        return [(document.title, document.content)]
    return [
        (heading, "\n".join(section_lines).strip())
        for heading, section_lines in sections
        if "\n".join(section_lines).strip()
    ]


def search_help_documents(
    query: str,
    *,
    top_k: int = 5,
    documents: list[HelpDocument] | None = None,
) -> list[HelpPassage]:
    """Rank bundled help sections for ``query`` without external services.

    A passage must cover at least 60% of the meaningful query concepts. This
    prevents a request for an unsupported integration from being presented as
    supported merely because a generic word such as "export" matched.
    """

    concepts = _query_concepts(query)
    if not concepts:
        return []

    required_matches = max(1, math.ceil(len(concepts) * 0.6))
    corpus = documents if documents is not None else load_product_help_articles()
    ranked: list[HelpPassage] = []

    for document in corpus:
        article_terms = Counter(_search_tokenize(f"{document.title} {document.slug}"))
        for heading, content in _article_sections(document):
            passage_terms = Counter(_search_tokenize(content))
            heading_terms = Counter(_search_tokenize(heading))
            matched = 0
            score = 0.0
            for concept in concepts:
                passage_frequency = max((passage_terms[term] for term in concept), default=0)
                heading_frequency = max((heading_terms[term] for term in concept), default=0)
                article_frequency = max((article_terms[term] for term in concept), default=0)
                if passage_frequency or heading_frequency or article_frequency:
                    matched += 1
                    score += min(passage_frequency, 3)
                    score += min(heading_frequency, 1) * 4
                    score += min(article_frequency, 1) * 2

            if matched < required_matches:
                continue
            # Prefer passages covering every concept, then break ties by lexical
            # density. The rounded score is stable and safe to expose to the model.
            coverage = matched / len(concepts)
            score += coverage * 10
            ranked.append(
                HelpPassage(
                    title=f"{document.title} — {heading}",
                    content=content,
                    source=f"docs/help/{document.slug}.md",
                    score=round(score, 4),
                )
            )

    ranked.sort(key=lambda passage: (-passage.score, passage.source, passage.title))
    return ranked[: max(1, min(top_k, 8))]


async def _existing_help_documents(
    db: AsyncSession,
    workspace_id: uuid.UUID,
) -> dict[str, KnowledgeDocument]:
    """Return this workspace's help documents keyed by slug."""

    result = await db.execute(
        select_workspace_owned(KnowledgeDocument, workspace_id).where(
            KnowledgeDocument.agent_id.is_(None),
            KnowledgeDocument.doc_type == PRODUCT_HELP_DOC_TYPE,
        )
    )
    by_slug: dict[str, KnowledgeDocument] = {}
    for document in result.scalars().all():
        slug = str(document.metadata_.get("slug") or "")
        if slug:
            by_slug[slug] = document
    return by_slug


async def sync_product_help(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    documents: list[HelpDocument] | None = None,
    embedder: Embedder | None = None,
    force: bool = False,
) -> ProductHelpSyncResult:
    """Upsert the help corpus into ``workspace_id`` and index it for retrieval.

    Runs inside the caller's transaction — the documents and their chunks commit
    or roll back together. Every row is workspace-scoped with ``agent_id`` NULL
    so ``search_help`` can retrieve it without impersonating a customer-facing
    agent, and so it can never leak into an agent's knowledge base.
    """

    corpus = documents if documents is not None else load_help_documents()
    existing = await _existing_help_documents(db, workspace_id)

    created = 0
    updated = 0
    indexed = 0
    skipped = 0

    for article in corpus:
        document = existing.get(article.slug)
        if document is None:
            document = KnowledgeDocument(
                workspace_id=workspace_id,
                agent_id=None,
                title=article.title,
                doc_type=PRODUCT_HELP_DOC_TYPE,
                content=article.content,
                token_count=knowledge_context_service.count_tokens(article.content),
                priority=0,
                is_active=True,
                metadata_={"slug": article.slug, "source": f"docs/help/{article.slug}.md"},
            )
            db.add(document)
            created += 1
        else:
            document.title = article.title
            document.content = article.content
            document.token_count = knowledge_context_service.count_tokens(article.content)
            document.is_active = True
            document.metadata_ = {
                **document.metadata_,
                "slug": article.slug,
                "source": f"docs/help/{article.slug}.md",
            }
            updated += 1

        # Flush so a newly added document has an id before its chunks reference it.
        await db.flush()
        result = await knowledge_ingestion_service.reindex_document(
            db,
            document,
            embedder=embedder,
            force=force,
        )
        if result.skipped:
            skipped += 1
        else:
            indexed += 1

    logger.info(
        "product_help_synced",
        workspace_id=str(workspace_id),
        created=created,
        updated=updated,
        indexed=indexed,
        skipped=skipped,
    )
    return ProductHelpSyncResult(
        workspace_id=workspace_id,
        created=created,
        updated=updated,
        indexed=indexed,
        skipped=skipped,
    )
