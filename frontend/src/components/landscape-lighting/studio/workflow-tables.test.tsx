import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { LandscapeScheduleRow } from "@/lib/estimator/landscape-schedule";

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
        name: /Fixture schedule with editable lamp and accessory assignments/i,
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
});
