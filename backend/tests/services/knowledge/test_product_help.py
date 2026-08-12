"""Bundled product-help source, lexical retrieval, and optional index sync.

The markdown is the evidence base for ``search_help``. These tests keep it
loadable, route-complete, relevant to representative operator questions, and
safe to sync as workspace-level documents when hybrid-index compatibility is
needed.
"""

from __future__ import annotations

import re
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
    search_help_documents,
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

    @pytest.mark.parametrize(
        ("question", "expected_source", "expected_text"),
        [
            (
                "How do I create and send an invoice?",
                "docs/help/sales-quotes-and-invoices.md",
                "**Create & send**",
            ),
            (
                "Where can I see my pipeline?",
                "docs/help/sales-quotes-and-invoices.md",
                "`/opportunities`",
            ),
            (
                "How do I import contacts?",
                "docs/help/contacts-and-communications.md",
                "**Import**",
            ),
            (
                "How do I receive inventory stock?",
                "docs/help/operations-and-service-delivery.md",
                "**Receive stock**",
            ),
        ],
    )
    def test_representative_questions_retrieve_supported_workflows(
        self,
        question: str,
        expected_source: str,
        expected_text: str,
    ) -> None:
        passages = search_help_documents(question, top_k=5)

        matches = [passage for passage in passages if passage.source == expected_source]
        assert matches, passages
        assert expected_text in "\n".join(passage.content for passage in matches)

    def test_unsupported_integration_does_not_match_a_nearby_export_workflow(self) -> None:
        assert search_help_documents("How do I export to QuickBooks?") == []

    def test_every_navigable_crm_route_is_in_the_help_source(self) -> None:
        repo_root = Path(__file__).resolve().parents[4]
        nav_source = (repo_root / "frontend/src/components/layout/app-nav.ts").read_text(
            encoding="utf-8"
        )
        nav_items = re.findall(
            r'title:\s*"([^"]+)"[\s\S]{0,120}?url:\s*"(/[^"]+)"',
            nav_source,
        )
        assert len(nav_items) >= 40
        corpus = "\n".join(document.content for document in load_help_documents())

        missing = sorted(
            (title, url)
            for title, url in nav_items
            if f"**{title}**" not in corpus or f"`{url.split('?', maxsplit=1)[0]}`" not in corpus
        )
        assert missing == []

    def test_every_user_facing_app_page_is_in_the_help_source(self) -> None:
        repo_root = Path(__file__).resolve().parents[4]
        app_root = repo_root / "frontend/src/app"
        page_routes: set[str] = set()
        for page in app_root.rglob("page.tsx"):
            segments = [
                segment
                for segment in page.relative_to(app_root).parts[:-1]
                if not (segment.startswith("(") and segment.endswith(")"))
            ]
            route = f"/{'/'.join(segments)}" if segments else "/"
            page_routes.add(re.sub(r"\[[^]]+\]", "{}", route))

        documented_routes = {
            re.sub(r"\{[^}]+\}", "{}", route.split("?", maxsplit=1)[0])
            for document in load_help_documents()
            for route in re.findall(r"`(/[^`\s]+)`", document.content)
        }
        intentionally_not_product_help = {"/", "/dev/components"}

        missing = sorted(page_routes - documented_routes - intentionally_not_product_help)
        assert missing == []

    def test_every_settings_tab_has_a_route_accurate_help_entry(self) -> None:
        repo_root = Path(__file__).resolve().parents[4]
        settings_source = (
            repo_root / "frontend/src/components/settings/settings-page.tsx"
        ).read_text(encoding="utf-8")
        settings_tabs = re.findall(r'\{ value: "([^"]+)", label: "([^"]+)"', settings_source)
        assert len(settings_tabs) >= 19
        corpus = "\n".join(document.content for document in load_help_documents())

        missing = [
            (value, label)
            for value, label in settings_tabs
            if f"`/settings?tab={value}`" not in corpus or f"**{label}**" not in corpus
        ]
        assert missing == []

    def test_backend_container_includes_the_help_source(self) -> None:
        repo_root = Path(__file__).resolve().parents[4]
        dockerfile = (repo_root / "backend/Dockerfile").read_text(encoding="utf-8")
        dockerignore = (repo_root / "backend/.dockerignore").read_text(encoding="utf-8")

        assert "COPY docs/ ./docs/" in dockerfile
        assert "COPY --from=builder --chown=app:app /app/docs /app/docs" in dockerfile
        assert "!docs/help/" in dockerignore
        assert "!docs/help/*.md" in dockerignore

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
