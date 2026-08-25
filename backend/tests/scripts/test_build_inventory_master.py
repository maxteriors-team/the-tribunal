from __future__ import annotations

import csv
import importlib.util
import shutil
from collections import Counter
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "backend" / "scripts" / "ops" / "build_inventory_master.py"
SOURCE_FILES = (
    "google-sheets-landscape-inventory-upload.csv",
    "google-sheets-bistro-inventory-upload.csv",
    "google-sheets-christmas-inventory-upload.csv",
)


def load_generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_inventory_master", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake_minleon_products() -> dict[str, dict]:
    colors = {
        "White": "W",
        "Sand": "S",
        "Light Brown": "LB",
        "Brown": "BR",
        "Grey": "G",
        "Black": "BK",
    }
    prices = {100: 134900, 150: 174900, 200: 219900, 400: 409900}
    variants = []
    variant_id = 1_000
    for length, price in prices.items():
        for color, code in colors.items():
            sku = f"KIT-CC-{length}{code}-D"
            if length == 400 and color == "White":
                sku = "KIT-CC-200W-D"
            elif length == 400 and color == "Brown":
                sku = "KIT-CC-200BR-D"
            variants.append(
                {
                    "id": variant_id,
                    "option1": f"{length} feet RGBW",
                    "option2": color,
                    "option3": "Dual Port Wec",
                    "sku": sku,
                    "price": price,
                }
            )
            variant_id += 1

    return {
        "100-ft-rgb-starter-pack-minleon-permanent-lighting-demo-kit": {
            "title": "RGBW+2 DEEP Pebble Complete Kits",
            "variants": variants,
        },
        "minleon-permanent-lighting-rgb-power-t": {
            "title": "Power-T",
            "variants": [
                {"id": 2_001, "option1": "Black", "sku": "RGB+PT-12B", "price": 2595},
                {"id": 2_002, "option1": "White", "sku": "RGB+PT-12W", "price": 2595},
                {"id": 2_003, "option1": "Sand", "sku": "RGB+PT-12S", "price": 2595},
            ],
        },
        "minleon-permanent-lighting-rgb-basic-4-pin-t": {
            "title": "Basic 4-Wire T",
            "variants": [
                {"id": 3_001, "option1": "Black", "sku": "RGB+BMT-4WB", "price": 995},
                {"id": 3_002, "option1": "White", "sku": "RGB+BMT-4WW", "price": 995},
                {"id": 3_003, "option1": "Sand", "sku": "RGB+BMT-4WS", "price": 995},
            ],
        },
        "minleon-permanent-lighting-rgb-signal-booster": {
            "title": "Signal Booster (2 pieces)",
            "variants": [
                {"id": 4_001, "option1": "Black", "sku": "RGB+2 SR", "price": 2500},
                {"id": 4_002, "option1": "White", "sku": "RGB+SRW", "price": 2500},
                {"id": 4_003, "option1": "Sand", "sku": "RGB+SRW", "price": 2500},
            ],
        },
        "minleon-permanent-lighting-power-supply": {
            "title": "Power Supply",
            "variants": [
                {
                    "id": 46626313797799,
                    "option1": "5 Amp Power Supply",
                    "sku": "RGB+5A-24V",
                    "price": 10495,
                }
            ],
        },
    }


def test_main_generates_unique_formula_safe_inventory_master(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    generator = load_generator()
    for filename in SOURCE_FILES:
        shutil.copy2(ROOT / "docs" / filename, tmp_path / filename)

    products = fake_minleon_products()
    monkeypatch.setattr(generator, "DOCS", tmp_path)
    monkeypatch.setattr(generator, "fetch_product", lambda handle: products[handle])

    generator.main()

    master_path = tmp_path / "google-sheets-all-inventory-upload.csv"
    permanent_path = tmp_path / "google-sheets-permanent-holiday-inventory-upload.csv"
    assert master_path.is_file()
    assert permanent_path.is_file()

    with master_path.open(newline="", encoding="utf-8") as file:
        master = list(csv.DictReader(file))
    with permanent_path.open(newline="", encoding="utf-8") as file:
        permanent = list(csv.DictReader(file))

    assert len(master) == 95
    assert len(permanent) == 35
    assert len({row["internal_sku"] for row in master}) == 95
    assert Counter(row["service_line"] for row in master) == {
        "permanent_holiday": 35,
        "christmas": 25,
        "landscape": 24,
        "bistro": 11,
    }
    assert Counter(row["record_type"] for row in master) == {
        "inventory_item": 92,
        "cost_rule": 3,
    }
    assert all(row["quantity_on_hand"] == "" for row in master)
    assert all(
        not value.lstrip().startswith(generator.SPREADSHEET_FORMULA_PREFIXES)
        for row in master
        for value in row.values()
    )


@pytest.mark.parametrize(
    "unsafe_value", ["=formula", "+formula", "-formula", "@formula", "\t=formula"]
)
def test_write_csv_rejects_formula_prefixes_before_creating_file(
    tmp_path: Path, unsafe_value: str
) -> None:
    generator = load_generator()
    row = dict.fromkeys(generator.FIELDS, "")
    row["internal_sku"] = unsafe_value
    output = tmp_path / "unsafe.csv"

    with pytest.raises(ValueError, match="spreadsheet formula prefix"):
        generator.write_csv(output, [row])

    assert not output.exists()
