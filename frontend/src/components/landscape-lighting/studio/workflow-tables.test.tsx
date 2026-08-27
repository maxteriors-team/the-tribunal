import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { LandscapeScheduleRow } from "@/lib/estimator/landscape-schedule";
import type { CatalogItemResponse } from "@/types/sales-wizard";

import { LandscapeFixtureScheduleTable } from "./workflow-tables";

const row: LandscapeScheduleRow = {
  number: 1,
  shotId: "sheet-front",
  itemId: "fixture-placed-1",
  productId: "fixture-uplight",
  sheetLabel: "L-1",
  fixtureType: "uplight",
  fixtureName: "ZD Uplight",
  fixtureCatalogItemId: "catalog-uplight",
  fixtureSku: "UP-1",
  lampCatalogItemId: "lamp-1",
  lampName: "MR16 Lamp",
  accessoryCatalogItemIds: ["shield-1"],
  accessoryNames: ["Glare shield"],
  unresolved: [],
};

describe("LandscapeFixtureScheduleTable", () => {
  it("labels all six fixture-type choices and clears overrides on change", () => {
    const onUpdate = vi.fn();
    render(
      <LandscapeFixtureScheduleTable
        rows={[row]}
        catalog={[]}
        onUpdate={onUpdate}
        onCopyToType={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("table", {
        name: /Fixture schedule with editable fixture type and product, lamp, and accessory assignments/i,
      }),
    ).toBeVisible();
    const select = screen.getByRole("combobox", { name: "Fixture type for fixture 1" });
    expect(select).toBe(screen.getByLabelText("Fixture type for fixture 1"));
    expect(
      within(select)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual(["Uplight", "In-grade", "Pathlight", "Downlight", "Wall light", "Underwater"]);

    select.focus();
    expect(select).toHaveFocus();
    fireEvent.change(select, { target: { value: "downlight" } });

    expect(onUpdate).toHaveBeenCalledWith("fixture-placed-1", {
      productId: "fixture-downlight",
      catalogItemId: undefined,
      catalogSku: undefined,
      lampCatalogItemId: undefined,
      accessoryCatalogItemIds: [],
    });
  });

  it("puts product selection with the fixture and keeps fixture products out of lamps", () => {
    const onUpdate = vi.fn();
    const catalog = [
      {
        id: "catalog-uplight",
        name: "Accent Uplight",
        sku: "UP-ACCENT",
        kind: "product",
        is_active: true,
        description: "Landscape accent fixture",
        attributes: { fixture_type: "uplight" },
      },
      {
        id: "lamp-1",
        name: "MR16 Lamp",
        sku: "MR16-7W",
        kind: "product",
        is_active: true,
        description: "Replaceable LED lamp",
      },
      {
        id: "transformer-1",
        name: "300W Transformer",
        sku: "TX-300",
        kind: "product",
        is_active: true,
      },
    ] as CatalogItemResponse[];

    render(
      <LandscapeFixtureScheduleTable
        rows={[row]}
        catalog={catalog}
        onUpdate={onUpdate}
        onCopyToType={vi.fn()}
      />,
    );

    const fixtureProduct = screen.getByRole("combobox", {
      name: "Fixture product for fixture 1",
    });
    expect(within(fixtureProduct).getByRole("option", { name: /Accent Uplight/i })).toBeVisible();
    expect(within(fixtureProduct).queryByRole("option", { name: /MR16/i })).toBeNull();
    expect(within(fixtureProduct).queryByRole("option", { name: /Transformer/i })).toBeNull();

    const lamp = screen.getByRole("combobox", { name: "Lamp for fixture 1" });
    expect(within(lamp).getByRole("option", { name: /MR16 Lamp/i })).toBeVisible();
    expect(within(lamp).queryByRole("option", { name: /Accent Uplight/i })).toBeNull();

    fireEvent.change(fixtureProduct, { target: { value: "catalog-uplight" } });
    expect(onUpdate).toHaveBeenCalledWith("fixture-placed-1", {
      catalogItemId: "catalog-uplight",
      catalogSku: "UP-ACCENT",
      lampCatalogItemId: undefined,
      accessoryCatalogItemIds: [],
    });
  });
});
