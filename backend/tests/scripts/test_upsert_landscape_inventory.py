from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from sqlalchemy.sql import Select

from app.models.catalog import CatalogItem
from app.models.inventory import InventoryItem
from app.models.workspace import Workspace
from scripts.ops import upsert_landscape_inventory as landscape_upsert

EXPECTED_SKUS = (
    "59009035",
    "59009050",
    "59203512",
    "59205842",
    "59213082",
    "59213092",
    "59213350",
    "59213632",
    "59213710",
    "59214042",
    "59272804",
    "59303512",
    "59304101",
    "59306832",
    "59308530",
    "59311122",
    "59320292",
    "59400232",
    "59403532",
    "59407330",
    "59409010",
    "59409312",
    "59412322",
    "59413032",
)


class FakeResult:
    def __init__(self, *, scalar: object | None = None, rows: list[object] | None = None) -> None:
        self.scalar = scalar
        self.rows = rows or []

    def scalar_one_or_none(self) -> object | None:
        return self.scalar

    def scalars(self) -> FakeResult:
        return self

    def all(self) -> list[object]:
        return self.rows


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
    def __init__(self, results: list[FakeResult], *, flush_error: Exception | None = None) -> None:
        self.results = iter(results)
        self.flush_error = flush_error
        self.statements: list[Select[Any]] = []
        self.added: list[object] = []
        self.transaction = FakeTransaction()
        self.flushes = 0

    async def begin(self) -> FakeTransaction:
        return self.transaction

    async def execute(self, statement: Select[Any]) -> FakeResult:
        self.statements.append(statement)
        return next(self.results)

    def add(self, item: object) -> None:
        self.added.append(item)

    async def flush(self) -> None:
        self.flushes += 1
        if self.flush_error is not None:
            raise self.flush_error


@asynccontextmanager
async def _session_factory(session: FakeSession) -> AsyncIterator[FakeSession]:
    yield session


def _workspace() -> Workspace:
    return Workspace(id=uuid.uuid4(), name="Maxteriors Lighting", slug="default", settings={})


def _catalog(workspace_id: uuid.UUID, sku: str) -> CatalogItem:
    return CatalogItem(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        name=f"Catalog {sku}",
        sku=sku,
        kind="product",
        unit_price=1,
    )


def _session_results(
    workspace: Workspace,
    *,
    items: list[InventoryItem] | None = None,
    catalog: list[CatalogItem] | None = None,
    owners: list[InventoryItem] | None = None,
) -> list[FakeResult]:
    catalog = catalog or []
    results = [
        FakeResult(scalar=workspace),
        FakeResult(rows=list(items or [])),
        FakeResult(rows=catalog),
    ]
    if catalog:
        results.append(FakeResult(rows=list(owners or [])))
    return results


def _run(
    monkeypatch: pytest.MonkeyPatch,
    session: FakeSession,
    *,
    apply: bool,
) -> landscape_upsert.ImportResult:
    monkeypatch.setattr(
        landscape_upsert,
        "AsyncSessionLocal",
        lambda: _session_factory(session),
    )
    return asyncio.run(landscape_upsert.upsert("default", apply=apply))


def test_all_24_reviewed_definitions_are_unique_and_zero_stock() -> None:
    definitions = landscape_upsert.LANDSCAPE_INVENTORY

    assert landscape_upsert.APPROVED_SKUS == EXPECTED_SKUS
    assert len(definitions) == len(set(landscape_upsert.APPROVED_SKUS)) == 24
    assert {item.review_group for item in definitions} == {"mapped", "unresolved"}
    assert sum(item.review_group == "mapped" for item in definitions) == 19
    assert sum(item.review_group == "unresolved" for item in definitions) == 5
    assert {item.sku for item in definitions if item.name_role_difference} == {
        "59213082",
        "59412322",
        "59413032",
    }
    assert landscape_upsert.CATALOG_LINK_SKUS == ("59306832", "59407330")

    workspace_id = uuid.uuid4()
    for definition in definitions:
        payload = landscape_upsert.inventory_item_payload(workspace_id, definition)
        assert payload == {
            "id": landscape_upsert.inventory_item_id(workspace_id, definition.sku),
            "workspace_id": workspace_id,
            "catalog_item_id": None,
            "name": definition.name,
            "sku": definition.sku,
            "unit_of_measure": "each",
            "is_active": True,
            "valuation_method": "weighted_average",
            "supplier_name": "FX Luminaire",
            "supplier_sku": definition.sku,
            "notes": None,
        }
        assert not ({"quantity", "source_quantity", "unit_cost"} & payload.keys())


def test_dry_run_stages_all_rows_then_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = _workspace()
    session = FakeSession(_session_results(workspace))

    result = _run(monkeypatch, session, apply=False)

    assert result.created == 24
    assert len(session.added) == 24
    assert session.flushes == 1
    assert session.transaction.rollbacks == 1
    assert session.transaction.commits == 0
    assert "DRY RUN — ROLLED BACK" in capsys.readouterr().out


def test_apply_commits_once_and_rolls_back_on_any_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace()
    committed = FakeSession(_session_results(workspace))

    _run(monkeypatch, committed, apply=True)

    assert committed.transaction.commits == 1
    assert committed.transaction.rollbacks == 0

    failed = FakeSession(_session_results(workspace), flush_error=RuntimeError("flush failed"))
    with pytest.raises(RuntimeError, match="flush failed"):
        _run(monkeypatch, failed, apply=True)
    assert failed.transaction.commits == 0
    assert failed.transaction.rollbacks == 1


def test_apply_is_idempotent_and_preserves_existing_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace()
    catalogs = [_catalog(workspace.id, sku) for sku in landscape_upsert.CATALOG_LINK_SKUS]
    first = FakeSession(_session_results(workspace, catalog=catalogs))

    first_result = _run(monkeypatch, first, apply=True)
    created = [item for item in first.added if isinstance(item, InventoryItem)]
    by_sku = {item.sku: item for item in created}

    assert first_result.created == 24
    assert first_result.linked == 2
    assert by_sku["59306832"].catalog_item_id == catalogs[0].id
    assert by_sku["59407330"].catalog_item_id == catalogs[1].id

    preserved = by_sku["59009035"]
    preserved.name = "Operator-renamed transformer"
    preserved.supplier_name = "Operator supplier"
    preserved.notes = "Operator note"
    second = FakeSession(
        _session_results(
            workspace,
            items=created,
            catalog=catalogs,
            owners=[by_sku["59306832"], by_sku["59407330"]],
        )
    )

    second_result = _run(monkeypatch, second, apply=True)

    assert second_result.created == 0
    assert second_result.kept == 24
    assert second_result.linked == 0
    assert second_result.kept_links == 2
    assert second.added == []
    assert preserved.name == "Operator-renamed transformer"
    assert preserved.supplier_name == "Operator supplier"
    assert preserved.notes == "Operator note"
    assert all('"existing_metadata": "preserved"' in line for line in second_result.manifest_lines)
    assert all('"quantity_on_hand"' not in line for line in second_result.manifest_lines)


def test_catalog_links_require_one_unowned_workspace_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace()
    wall = _catalog(workspace.id, "59306832")
    underwater_a = _catalog(workspace.id, "59407330")
    underwater_b = _catalog(workspace.id, "59407330")
    owner = InventoryItem(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        name="Existing tracked catalog item",
        sku="OTHER",
        catalog_item_id=wall.id,
    )
    session = FakeSession(
        _session_results(
            workspace,
            catalog=[wall, underwater_a, underwater_b],
            owners=[owner],
        )
    )

    result = _run(monkeypatch, session, apply=True)
    by_sku = {item.sku: item for item in session.added if isinstance(item, InventoryItem)}

    assert result.linked == 0
    assert result.blocked_links == 2
    assert by_sku["59306832"].catalog_item_id is None
    assert by_sku["59407330"].catalog_item_id is None
    assert "owned_by:OTHER" in next(line for line in result.manifest_lines if "59306832" in line)
    assert "catalog_ambiguous" in next(line for line in result.manifest_lines if "59407330" in line)


def test_every_inventory_and_catalog_query_and_write_is_workspace_scoped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace()
    catalogs = [_catalog(workspace.id, sku) for sku in landscape_upsert.CATALOG_LINK_SKUS]
    session = FakeSession(_session_results(workspace, catalog=catalogs))

    _run(monkeypatch, session, apply=True)

    statements = [str(statement) for statement in session.statements]
    assert "workspaces.slug" in statements[0]
    assert all("workspace_id" in statement for statement in statements[1:])
    assert all(item.workspace_id == workspace.id for item in session.added)
    assert not any("inventory_ledger_entries" in statement for statement in statements)
    assert not any("inventory_stock_levels" in statement for statement in statements)
    assert all(isinstance(item, InventoryItem) for item in session.added)
