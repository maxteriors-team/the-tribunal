from __future__ import annotations

import asyncio
import csv
import uuid
from collections import Counter
from collections.abc import AsyncIterator, Iterator, Sequence
from contextlib import asynccontextmanager
from typing import Any

import pytest
from sqlalchemy.sql import Select

from app.models.catalog import CatalogItem
from app.models.inventory import InventoryItem
from app.models.workspace import Workspace
from scripts.ops import upsert_landscape_inventory as landscape_upsert

REVIEWED_LANDSCAPE_SKUS = (
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
STOCK_ROWS = 92
COST_RULE_ROWS = 3


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
        # A real ScalarResult iterates; the fake must too or it hides bugs.
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
    moved: list[InventoryItem] | None = None,
) -> list[FakeResult]:
    catalog = catalog or []
    moved_ids = [item.id for item in moved or []]
    # Query order mirrors _build_import: workspace, items, catalog, catalog
    # owners, then one pass per stock table (ledger, then stock levels).
    results = [
        FakeResult(scalar=workspace),
        FakeResult(rows=list(items or [])),
        FakeResult(rows=catalog),
    ]
    if catalog:
        results.append(FakeResult(rows=list(owners or [])))
    if items:
        results.append(FakeResult(rows=moved_ids))
        results.append(FakeResult(rows=[]))
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


def _sheet_rows() -> list[dict[str, str]]:
    with landscape_upsert.INVENTORY_CSV.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _write_sheet(source: Any, rows: list[dict[str, str]]) -> Any:
    with source.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return source


def test_definitions_cover_every_stock_row_and_exclude_cost_rules() -> None:
    definitions = landscape_upsert.load_definitions()
    rows = _sheet_rows()

    assert len(rows) == STOCK_ROWS + COST_RULE_ROWS
    assert sum(row["record_type"] == "cost_rule" for row in rows) == COST_RULE_ROWS
    assert len(definitions) == STOCK_ROWS
    assert len({item.sku for item in definitions}) == STOCK_ROWS
    cost_rule_skus = {row["internal_sku"] for row in rows if row["record_type"] == "cost_rule"}
    assert cost_rule_skus and not (cost_rule_skus & {item.sku for item in definitions})

    assert Counter(item.service_line for item in definitions) == {
        "landscape": 24,
        "bistro": 11,
        "permanent_holiday": 35,
        "christmas": 22,
    }


def test_landscape_review_outcomes_survive_the_wider_sheet() -> None:
    by_sku = {item.sku: item for item in landscape_upsert.load_definitions()}

    assert tuple(sorted(landscape_upsert.LANDSCAPE_REVIEW)) == tuple(
        sorted(REVIEWED_LANDSCAPE_SKUS)
    )
    assert sum(by_sku[sku].review_group == "mapped" for sku in REVIEWED_LANDSCAPE_SKUS) == 19
    assert sum(by_sku[sku].review_group == "unresolved" for sku in REVIEWED_LANDSCAPE_SKUS) == 5
    assert {sku for sku, item in by_sku.items() if item.name_role_difference} == {
        "59213082",
        "59412322",
        "59413032",
    }
    assert {sku for sku, item in by_sku.items() if item.catalog_link} == {"59306832", "59407330"}
    # The review withheld per-foot valuation, so the sheet's `ft` is not adopted.
    assert by_sku["59272804"].unit_of_measure == "each"
    assert {item.review_group for item in by_sku.values()} == {
        "mapped",
        "unresolved",
        "needs_physical_count",
    }


def test_payload_is_zero_stock_and_never_invents_a_supplier() -> None:
    definitions = landscape_upsert.load_definitions()
    workspace_id = uuid.uuid4()

    # Only the unsourced garland stays blank; the reviewed supplier covers the
    # 24 landscape rows and is never applied to another service line.
    blank_supplier = [item.sku for item in definitions if item.supplier_name is None]
    assert blank_supplier == ["XMAS-GARLAND-PRELIT-9"]
    landscape = [item for item in definitions if item.service_line == "landscape"]
    assert len(landscape) == 24
    assert all(item.supplier_name == "FX Luminaire" for item in landscape)
    assert not any(
        item.supplier_name == "FX Luminaire"
        for item in definitions
        if item.service_line != "landscape"
    )

    for definition in definitions:
        payload = landscape_upsert.inventory_item_payload(workspace_id, definition)
        assert payload == {
            "id": landscape_upsert.inventory_item_id(workspace_id, definition.sku),
            "workspace_id": workspace_id,
            "catalog_item_id": None,
            "name": definition.name,
            "sku": definition.sku,
            "unit_of_measure": definition.unit_of_measure,
            "is_active": True,
            "valuation_method": "weighted_average",
            "supplier_name": definition.supplier_name,
            "supplier_sku": definition.supplier_sku,
            "notes": None,
        }
        assert payload["notes"] is None
        assert not ({"quantity", "source_quantity", "unit_cost"} & payload.keys())


def test_dry_run_stages_all_rows_then_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = _workspace()
    session = FakeSession(_session_results(workspace))

    result = _run(monkeypatch, session, apply=False)

    assert result.created == STOCK_ROWS
    assert result.updated == 0
    assert result.skipped == 0
    assert len(session.added) == STOCK_ROWS
    assert session.flushes == 1
    assert session.transaction.rollbacks == 1
    assert session.transaction.commits == 0
    out = capsys.readouterr().out
    assert "DRY RUN — ROLLED BACK" in out
    assert result.missing_supplier == ("XMAS-GARLAND-PRELIT-9",)
    assert "Supplier missing (left blank, needs a human value): 1" in out
    assert out.count("! supplier_name blank: ") == 1
    assert sum(line.startswith("- ") for line in out.splitlines()) == STOCK_ROWS


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
    catalogs = [_catalog(workspace.id, sku) for sku in ("59306832", "59407330")]
    first = FakeSession(_session_results(workspace, catalog=catalogs))

    first_result = _run(monkeypatch, first, apply=True)
    created = [item for item in first.added if isinstance(item, InventoryItem)]
    by_sku = {item.sku: item for item in created}

    assert first_result.created == STOCK_ROWS
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
    assert second_result.updated == 0
    assert second_result.skipped == STOCK_ROWS
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
    catalogs = [_catalog(workspace.id, sku) for sku in ("59306832", "59407330")]
    session = FakeSession(_session_results(workspace, catalog=catalogs))

    _run(monkeypatch, session, apply=True)

    statements = [str(statement) for statement in session.statements]
    added = [item for item in session.added if isinstance(item, InventoryItem)]
    assert "workspaces.slug" in statements[0]
    # Assert the filter is in the WHERE clause: a bare `workspace_id` substring
    # also matches the selected column list, so it would pass unscoped queries.
    predicates = [statement.partition("WHERE")[2] for statement in statements[1:]]
    assert len(predicates) == 3
    assert all(".workspace_id = :workspace_id_1" in predicate for predicate in predicates)
    assert len(added) == len(session.added) == STOCK_ROWS
    assert all(item.workspace_id == workspace.id for item in added)
    assert not any("inventory_ledger_entries" in statement for statement in statements)
    assert not any("inventory_stock_levels" in statement for statement in statements)


def test_no_definition_name_crams_two_candidates_into_one_field() -> None:
    definitions = landscape_upsert.load_definitions()

    assert not [item.sku for item in definitions if "|" in item.name]
    by_sku = {item.sku: item.name for item in definitions}
    assert by_sku["59213092"] == "ZD Uplight"
    assert by_sku["59213350"] == "CORA In-Grade"
    assert by_sku["59213632"] == "ZDC Path Light"


def test_stale_piped_name_is_replaced_but_an_operator_rename_is_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace()
    stale = InventoryItem(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        name="ZD Uplight | Accent Uplight",
        sku="59213092",
        unit_of_measure="each",
    )
    renamed = InventoryItem(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        name="Front-bed accent (crew name)",
        sku="59213350",
        unit_of_measure="each",
    )
    session = FakeSession(_session_results(workspace, items=[stale, renamed]))

    result = _run(monkeypatch, session, apply=True)

    assert stale.name == "ZD Uplight"
    assert renamed.name == "Front-bed accent (crew name)"
    assert result.updated == 1
    assert result.skipped == 1


def test_sheet_spells_the_per_foot_unit_one_way() -> None:
    definitions = landscape_upsert.load_definitions()
    sheet_units = {
        row["stock_uom"] for row in _sheet_rows() if row["record_type"] == "inventory_item"
    }

    assert "linear_ft" in sheet_units
    assert not any(item.unit_of_measure == "linear_ft" for item in definitions)
    assert {item.sku for item in definitions if item.unit_of_measure == "ft"} == {
        "105P",
        "255C",
        "B0C1F3ZVXS",
        "XMAS-C7-SOCKET-GRN-24",
        "XMAS-C9-SOCKET-GRN-15",
        "XMAS-WIRE-GREEN-NOSOCKET",
    }


def test_unit_correction_lands_only_while_an_item_has_never_held_stock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace()
    never_stocked = InventoryItem(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        name="C9 Green Socket Wire — 15in Spacing",
        sku="XMAS-C9-SOCKET-GRN-15",
        unit_of_measure="linear_ft",
    )
    counted = InventoryItem(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        name="C7 Green Socket Wire — 24in Spacing with Integrated Clips (Trees Over 25 ft)",
        sku="XMAS-C7-SOCKET-GRN-24",
        unit_of_measure="linear_ft",
    )
    session = FakeSession(
        _session_results(workspace, items=[never_stocked, counted], moved=[counted])
    )

    result = _run(monkeypatch, session, apply=True)

    assert never_stocked.unit_of_measure == "ft"
    # Rewriting the unit under a counted balance would reinterpret the quantity.
    assert counted.unit_of_measure == "linear_ft"
    assert result.updated == 1
    assert result.skipped == 1
    assert result.created == STOCK_ROWS - 2


def test_sheet_vendor_wins_over_the_reviewed_supplier(tmp_path: Any) -> None:
    rows = _sheet_rows()
    for row in rows:
        if row["internal_sku"] == "59009035":
            row["vendor"] = "Ewing"
    source = _write_sheet(tmp_path / "revendored.csv", rows)

    by_sku = {item.sku: item for item in landscape_upsert.load_definitions(source)}

    assert by_sku["59009035"].supplier_name == "Ewing"
    assert by_sku["59009050"].supplier_name == "FX Luminaire"


def test_sheet_drift_that_drops_a_reviewed_sku_fails_loudly(tmp_path: Any) -> None:
    rows = [row for row in _sheet_rows() if row["internal_sku"] != "59009035"]
    source = tmp_path / "drifted.csv"
    with source.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    with pytest.raises(SystemExit, match="59009035"):
        landscape_upsert.load_definitions(source)
