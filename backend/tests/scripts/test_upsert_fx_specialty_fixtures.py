from __future__ import annotations

import asyncio
import copy
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from scripts.demo.seed_lighting_workspace import PRICING
from scripts.ops import upsert_fx_specialty_fixtures as specialty_upsert
from scripts.ops.upsert_fx_specialty_fixtures import (
    SPECIALTY_SECTION_TITLE,
    SPECIALTY_SKUS,
    merge_premier_specialty_section,
    specialty_catalog_payload,
)


def test_specialty_catalog_payload_keeps_customer_price_and_procurement_cost_separate() -> None:
    wall = specialty_catalog_payload("59306832")
    underwater = specialty_catalog_payload("59407330")

    assert wall["unit_price"] == 775
    assert wall["attributes"]["unit_cost"] == 166.76
    assert wall["attributes"]["fixture_type"] == "walllight"
    assert wall["attributes"]["core_drill_required"] is True
    assert wall["components"] == [
        {"sku": "59306832", "description": "PO-ZD-1LED-RD-FB Wall Light", "qty": 1}
    ]

    assert underwater["unit_price"] == 1295
    assert underwater["attributes"]["unit_cost"] == 374.37
    assert underwater["attributes"]["list_price"] == 664.95
    assert underwater["attributes"]["fixture_type"] == "underwater"
    assert underwater["attributes"]["fixture_watts"] == 9.1
    assert underwater["components"] == [
        {"sku": "59407330", "description": "LL-ZDC-BS Underwater Light", "qty": 1}
    ]


def test_merge_premier_specialty_section_is_preserving_and_idempotent() -> None:
    original = copy.deepcopy(PRICING)
    premier = next(tier for tier in original["tiers"] if tier["key"] == "best")
    premier["sections"] = [
        section for section in premier["sections"] if section["title"] != SPECIALTY_SECTION_TITLE
    ]
    original["operator_custom_setting"] = {"keep": True}

    merged, changed = merge_premier_specialty_section(original)
    merged_again, changed_again = merge_premier_specialty_section(merged)

    assert changed is True
    assert changed_again is False
    assert original["tiers"][0]["sections"][-1]["title"] != SPECIALTY_SECTION_TITLE
    assert merged["operator_custom_setting"] == {"keep": True}
    assert merged_again == merged

    premier = next(tier for tier in merged["tiers"] if tier["key"] == "best")
    specialty = next(
        section for section in premier["sections"] if section["title"] == SPECIALTY_SECTION_TITLE
    )
    assert specialty["item_ids"] == list(SPECIALTY_SKUS)


def test_merge_requires_an_existing_premier_tier() -> None:
    pricing = copy.deepcopy(PRICING)
    pricing["tiers"] = [tier for tier in pricing["tiers"] if tier["key"] != "best"]

    with pytest.raises(ValueError, match="Premier"):
        merge_premier_specialty_section(pricing)


def test_dry_run_prints_after_rollback_expires_workspace(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class WorkspaceStub:
        id = uuid.uuid4()
        name = "Default Workspace"
        slug = "default"
        settings = {specialty_upsert.SETTINGS_KEY: copy.deepcopy(PRICING)}
        expired = False

        def __getattribute__(self, name: str) -> object:
            if name in {"name", "slug"} and object.__getattribute__(self, "expired"):
                raise AssertionError(f"expired workspace field accessed: {name}")
            return object.__getattribute__(self, name)

    workspace = WorkspaceStub()
    workspace_result = MagicMock()
    workspace_result.scalar_one_or_none.return_value = workspace
    catalog_result = MagicMock()
    catalog_result.scalars.return_value.all.return_value = []
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[workspace_result, catalog_result])

    async def expire_workspace() -> None:
        workspace.expired = True

    db.rollback = AsyncMock(side_effect=expire_workspace)
    db.commit = AsyncMock()

    @asynccontextmanager
    async def fake_session():
        yield db

    monkeypatch.setattr(specialty_upsert, "AsyncSessionLocal", fake_session)

    asyncio.run(specialty_upsert.upsert(str(workspace.id), apply=False))

    output = capsys.readouterr().out
    assert "DRY RUN for workspace 'Default Workspace' (default)" in output
    assert "create 59306832" in output
    assert "create 59407330" in output
    db.rollback.assert_awaited_once()
    db.commit.assert_not_awaited()
