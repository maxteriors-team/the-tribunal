"""The bundled product-help corpus and its workspace-scoped sync.

The corpus is the evidence base for ``search_help``. If it stops loading, stops
covering the questions operators actually ask, or stops writing itself as
workspace-level (``agent_id IS NULL``) documents, the assistant silently goes
back to answering product questions from model priors — which reads as a
confident wrong answer, not as a failure.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.models.knowledge_document import KnowledgeDocument
from app.services.knowledge.product_help import (
    PRODUCT_HELP_DOC_TYPE,
    HelpDocument,
    ProductHelpError,
    load_help_documents,
    sync_product_help,
)


class TestCorpus:
    def test_every_article_loads_with_a_title_and_body(self) -> None:
        documents = load_help_documents()

        assert documents
        for document in documents:
            assert document.slug
            assert document.title
            assert not document.title.startswith("#")
            assert len(document.content) > 200

    def test_slugs_are_unique(self) -> None:
        slugs = [document.slug for document in load_help_documents()]

        assert len(slugs) == len(set(slugs))

    @pytest.mark.parametrize(
        ("slug", "must_mention"),
        [
            ("automations", "trigger"),
            ("campaigns", "automation"),
            ("approvals", "approve"),
            ("phone-numbers", "telnyx"),
            ("messaging-compliance", "quiet hours"),
        ],
    )
    def test_corpus_answers_the_how_to_eval_questions(self, slug: str, must_mention: str) -> None:
        """Each how_to golden case has a home in the corpus."""
        documents = {document.slug: document for document in load_help_documents()}

        assert slug in documents
        assert must_mention in documents[slug].content.lower()

    def test_every_article_lists_the_questions_it_answers(self) -> None:
        """Keyword retrieval uses AND semantics, so phrasing has to be present.

        ``websearch_to_tsquery`` requires every non-stopword term to appear in a
        chunk. Before each article listed the natural phrasings, "how do I set
        up an automation in this CRM?" matched **nothing** in the keyword arm —
        the corpus never said "CRM" — leaving ranking entirely to embeddings.
        """
        for document in load_help_documents():
            assert "## Questions this answers" in document.content, document.slug
            questions = [
                line for line in document.content.splitlines() if line.strip().endswith("?")
            ]
            assert len(questions) >= 4, document.slug

    def test_missing_directory_fails_loudly(self, tmp_path: Path) -> None:
        with pytest.raises(ProductHelpError):
            load_help_documents(tmp_path / "nope")

    def test_empty_directory_fails_loudly(self, tmp_path: Path) -> None:
        with pytest.raises(ProductHelpError):
            load_help_documents(tmp_path)

    def test_title_comes_from_the_first_heading(self, tmp_path: Path) -> None:
        (tmp_path / "widgets.md").write_text("# Working with widgets\n\nBody.\n")

        documents = load_help_documents(tmp_path)

        assert documents[0].slug == "widgets"
        assert documents[0].title == "Working with widgets"


def _db_returning(documents: list[KnowledgeDocument]) -> AsyncMock:
    db = AsyncMock()
    result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: documents))
    db.execute.return_value = result
    return db


@pytest.fixture
def article() -> HelpDocument:
    return HelpDocument(slug="widgets", title="Widgets", content="How widgets work.")


class TestSync:
    @pytest.mark.asyncio
    async def test_new_documents_are_workspace_scoped(
        self,
        article: HelpDocument,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        workspace_id = uuid.uuid4()
        db = _db_returning([])
        added: list[KnowledgeDocument] = []
        db.add = added.append  # type: ignore[method-assign]

        reindex = AsyncMock(return_value=SimpleNamespace(skipped=False, chunk_count=1))
        monkeypatch.setattr(
            "app.services.knowledge.product_help.knowledge_ingestion_service.reindex_document",
            reindex,
        )

        result = await sync_product_help(db, workspace_id, documents=[article])

        assert result.created == 1
        assert result.updated == 0
        assert result.indexed == 1
        document = added[0]
        # agent_id NULL is the whole point: product help belongs to the
        # workspace, not to a customer-facing agent.
        assert document.agent_id is None
        assert document.workspace_id == workspace_id
        assert document.doc_type == PRODUCT_HELP_DOC_TYPE
        assert document.metadata_["slug"] == "widgets"
        assert document.token_count > 0
        reindex.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_existing_documents_are_updated_not_duplicated(
        self,
        article: HelpDocument,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        workspace_id = uuid.uuid4()
        existing = KnowledgeDocument(
            workspace_id=workspace_id,
            agent_id=None,
            title="Old title",
            doc_type=PRODUCT_HELP_DOC_TYPE,
            content="Stale body.",
            token_count=2,
            metadata_={"slug": "widgets"},
        )
        db = _db_returning([existing])
        added: list[KnowledgeDocument] = []
        db.add = added.append  # type: ignore[method-assign]

        monkeypatch.setattr(
            "app.services.knowledge.product_help.knowledge_ingestion_service.reindex_document",
            AsyncMock(return_value=SimpleNamespace(skipped=True, chunk_count=1)),
        )

        result = await sync_product_help(db, workspace_id, documents=[article])

        assert added == []
        assert result.created == 0
        assert result.updated == 1
        assert result.skipped == 1
        assert existing.title == "Widgets"
        assert existing.content == "How widgets work."

    @pytest.mark.asyncio
    async def test_sync_only_reads_workspace_level_help_documents(
        self,
        article: HelpDocument,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db = _db_returning([])
        db.add = lambda _document: None  # type: ignore[method-assign]
        monkeypatch.setattr(
            "app.services.knowledge.product_help.knowledge_ingestion_service.reindex_document",
            AsyncMock(return_value=SimpleNamespace(skipped=False, chunk_count=1)),
        )

        await sync_product_help(db, uuid.uuid4(), documents=[article])

        statement: Any = db.execute.await_args.args[0]
        sql = str(statement.compile(compile_kwargs={"literal_binds": True})).lower()
        assert "knowledge_documents.workspace_id =" in sql
        assert "knowledge_documents.agent_id is null" in sql
        assert f"doc_type = '{PRODUCT_HELP_DOC_TYPE}'" in sql
