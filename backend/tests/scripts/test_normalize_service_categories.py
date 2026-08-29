from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Iterator, Sequence
from contextlib import asynccontextmanager
from typing import Any

import pytest

from app.models.catalog import CatalogItem
from app.models.quote import Quote, QuoteLineItem
from app.models.workspace import Workspace
from scripts.ops import normalize_service_categories as normalizer


class FakeResult:
    def __init__(
        self, *, scalar: object | None = None, rows: Sequence[object] | None = None
    ) -> None:
        self.scalar = scalar
        self.rows: list[object] = list(rows or [])

    def scalar_one_or_none(self) -> object | None:
        return self.scalar

    def scalars(self) -> FakeResult:
        return self

    def all(self) -> list[object]:
        return self.rows

    def __iter__(self) -> Iterator[object]:
        return iter(self.rows)


class FakeTransaction:
    def __init__(self) -> None:
        self.is_active = True
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1
        self.is_active = False

    async def rollback(self) -> None:
        self.rollbacks += 1
        self.is_active = False


class FakeSession:
    def __init__(self, results: list[FakeResult]) -> None:
        self.results = iter(results)
        self.statements: list[Any] = []
        self.transaction = FakeTransaction()

    async def begin(self) -> FakeTransaction:
        return self.transaction

    async def execute(self, statement: Any) -> FakeResult:
        self.statements.append(statement)
        return next(self.results)

    async def flush(self) -> None:
        return None


@asynccontextmanager
async def _session_factory(session: FakeSession) -> AsyncIterator[FakeSession]:
    yield session


def _workspace() -> Workspace:
    return Workspace(id=uuid.uuid4(), name="Maxteriors Lighting", slug="default", settings={})


def _catalog(workspace_id: uuid.UUID, sku: str, category: str | None) -> CatalogItem:
    return CatalogItem(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        name=f"Item {sku}",
        sku=sku,
        kind="product",
        unit_price=100,
        service_category=category,
    )


def _line(name: str, category: str | None, total: float = 100.0) -> QuoteLineItem:
    return QuoteLineItem(
        id=uuid.uuid4(),
        name=name,
        quantity=1,
        unit_price=total,
        discount=0,
        total=total,
        service_category=category,
    )


def _quote(
    workspace_id: uuid.UUID, number: str, lines: list[QuoteLineItem], **kwargs: Any
) -> Quote:
    quote = Quote(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        number=number,
        **kwargs,
    )
    quote.line_items = lines
    return quote


def _run(
    monkeypatch: pytest.MonkeyPatch,
    session: FakeSession,
    *,
    apply: bool,
) -> normalizer.NormalizeResult:
    monkeypatch.setattr(normalizer, "AsyncSessionLocal", lambda: _session_factory(session))
    return asyncio.run(normalizer.normalize("default", apply=apply))


def _results(
    workspace: Workspace,
    *,
    catalog: list[CatalogItem] | None = None,
    quotes: list[Quote] | None = None,
) -> list[FakeResult]:
    return [
        FakeResult(scalar=workspace),
        FakeResult(rows=list(catalog or [])),
        FakeResult(rows=list(quotes or [])),
    ]


def test_only_a_declared_alias_is_folded() -> None:
    assert normalizer.canonical_for("landscape") == "Landscape Lighting"
    # Case and surrounding space are drift too, not a different service.
    assert normalizer.canonical_for("  LANDSCAPE ") == "Landscape Lighting"
    # Already canonical: nothing to write.
    assert normalizer.canonical_for("Landscape Lighting") is None
    assert normalizer.canonical_for(None) is None
    # Undeclared categories are left exactly as typed, however similar they look.
    assert normalizer.canonical_for("landscaping") is None
    assert normalizer.canonical_for("Landscape Design") is None
    assert normalizer.canonical_for("Christmas Lighting") is None


def test_the_canonical_name_matches_what_onboarding_seeds() -> None:
    from app.services.workspaces import default_sales_setup

    source = (default_sales_setup.__file__ or "").replace(".pyc", ".py")
    with open(source, encoding="utf-8") as handle:
        seeded = handle.read()

    # If onboarding ever renames the service, this script must be renamed with
    # it or it will fold live data onto a spelling nothing else uses.
    for canonical in set(normalizer.CATEGORY_ALIASES.values()):
        assert f'service_category="{canonical}"' in seeded


def test_dry_run_stages_every_rename_then_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = _workspace()
    drifted = _catalog(workspace.id, "59306832", "landscape")
    canonical = _catalog(workspace.id, "OTHER", "Landscape Lighting")
    untouched = _catalog(workspace.id, "XMAS", "Christmas Lighting")
    quote = _quote(
        workspace.id,
        "QUO-000023",
        [_line("FX ZD Wall Light", "landscape", 900.0)],
        primary_service="landscape",
        attach_count=0,
        attach_value=0.0,
    )
    session = FakeSession(
        _results(workspace, catalog=[drifted, canonical, untouched], quotes=[quote])
    )

    result = _run(monkeypatch, session, apply=False)

    assert result.catalog_updated == 1
    assert result.line_items_updated == 1
    assert result.quotes_recomputed == 1
    assert untouched.service_category == "Christmas Lighting"
    assert canonical.service_category == "Landscape Lighting"
    assert session.transaction.rollbacks == 1
    assert session.transaction.commits == 0
    assert "DRY RUN — ROLLED BACK" in capsys.readouterr().out


def test_apply_commits_and_recomputes_the_quote_from_its_corrected_lines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace()
    quote = _quote(
        workspace.id,
        "QUO-000023",
        [_line("FX ZD Wall Light", "landscape", 900.0), _line("Gutter guard", "Gutters", 300.0)],
        primary_service="landscape",
        attach_count=1,
        attach_value=300.0,
    )
    session = FakeSession(_results(workspace, quotes=[quote]))

    result = _run(monkeypatch, session, apply=True)

    assert [line.service_category for line in quote.line_items] == [
        "Landscape Lighting",
        "Gutters",
    ]
    # Derived fields come back through compute_attach_metrics, not a rename:
    # the larger category still wins the primary slot and attach is unchanged.
    assert quote.primary_service == "Landscape Lighting"
    assert quote.attach_count == 1
    assert quote.attach_value == 300.0
    assert result.quotes_recomputed == 1
    assert session.transaction.commits == 1
    assert session.transaction.rollbacks == 0


def test_a_quote_with_no_drifted_line_is_left_completely_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace()
    quote = _quote(
        workspace.id,
        "QUO-000099",
        [_line("Gutter guard", "Gutters", 300.0)],
        primary_service="Gutters",
        attach_count=0,
        attach_value=0.0,
    )
    session = FakeSession(_results(workspace, quotes=[quote]))

    result = _run(monkeypatch, session, apply=True)

    assert result.line_items_updated == 0
    assert result.quotes_recomputed == 0
    assert quote.primary_service == "Gutters"


def test_every_read_is_scoped_to_one_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = _workspace()
    session = FakeSession(_results(workspace))

    _run(monkeypatch, session, apply=True)

    statements = [str(statement) for statement in session.statements]
    assert "workspaces.slug" in statements[0]
    # Assert the filter is in the WHERE clause: a bare `workspace_id` substring
    # also matches the selected column list, so it would pass unscoped queries.
    predicates = [statement.partition("WHERE")[2] for statement in statements[1:]]
    assert len(predicates) == 2
    assert all(".workspace_id = :workspace_id_1" in predicate for predicate in predicates)


def test_a_missing_workspace_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    session = FakeSession([FakeResult(scalar=None)])

    with pytest.raises(SystemExit, match="Workspace not found"):
        _run(monkeypatch, session, apply=True)

    assert session.transaction.commits == 0
    assert session.transaction.rollbacks == 1
