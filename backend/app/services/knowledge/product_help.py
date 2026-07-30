"""Workspace-level product help corpus — the source for ``search_help``.

Before this existed, "how do I set up an automation?" had no grounded answer.
Every ``KnowledgeDocument`` belonged to a customer-facing agent and held
per-tenant *business* material (faq/pricing/policy) for answering *contacts*, so
the assistant had to either refuse or answer product questions from model
priors — while its own prompt forbids inventing facts.

This module ships an operator-facing help corpus as markdown and syncs it into
the workspace-scoped side of the same hybrid retrieval stack the voice/text
agents already use: ``KnowledgeDocument`` rows with ``agent_id IS NULL``.

The markdown lives under ``backend/docs/help`` rather than the repo-root
``docs/`` tree on purpose: production deploys upload the ``backend/`` folder
only, so a repo-root path would simply not exist on the server.

Sync is idempotent. Documents are matched on their ``slug`` (the filename), so
re-running updates content in place instead of duplicating it, and the
ingestion service skips re-embedding when a document's chunk hashes are
unchanged.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
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
    for path in sorted(source.glob("*.md")):
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            continue
        documents.append(
            HelpDocument(
                slug=path.stem,
                title=_title_from_markdown(content, path.stem.replace("-", " ").title()),
                content=content,
            )
        )

    if not documents:
        raise ProductHelpError(f"Help corpus directory has no markdown files: {source}")
    return documents


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
