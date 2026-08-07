import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { UpsellAddonRow } from "@/components/upsell/upsell-addon-row";
import type { UpsellCatalogItem } from "@/lib/api/upsell";

/**
 * The add-on row is what a technician reads a price off of out loud, so this
 * suite pins the thing that makes that price honest — the rate unit — plus the
 * selection semantics a screen reader depends on.
 */

function makeItem(overrides: Partial<UpsellCatalogItem> = {}): UpsellCatalogItem {
  return {
    id: "item-1",
    name: "Landscape lighting install",
    description: "Six path lights and a transformer.",
    unit_price: 2400,
    taxable: true,
    service_category: "landscape",
    attach_targets: [],
    ...overrides,
  };
}

function renderRow(
  item: UpsellCatalogItem,
  quantity = 0,
  handlers: { onToggle?: () => void; onQuantityChange?: (n: number) => void } = {},
) {
  return render(
    <ul>
      <UpsellAddonRow
        item={item}
        quantity={quantity}
        onToggle={handlers.onToggle ?? vi.fn()}
        onQuantityChange={handlers.onQuantityChange ?? vi.fn()}
      />
    </ul>,
  );
}

describe("UpsellAddonRow", () => {
  it("labels a per-unit rate so it cannot be read as a job total", () => {
    // Without the unit, "$18.50" is the number a technician quotes for a patio
    // that actually prices out near $900.
    renderRow(
      makeItem({
        name: "Bistro lights",
        unit_price: 18.5,
        price_unit: "per linear foot",
      }),
    );

    expect(screen.getByText("$18.50")).toBeInTheDocument();
    expect(screen.getByText("per linear foot")).toBeInTheDocument();
  });

  it("does not invent a unit for a flat-priced item", () => {
    renderRow(makeItem());
    expect(screen.queryByText(/per linear foot/)).not.toBeInTheDocument();
  });

  it("never shows a job minimum — minimums are for whole systems, not upgrades", () => {
    renderRow(makeItem({ unit_price: 18.5, price_unit: "per linear foot" }));
    expect(screen.queryByText(/minimum/i)).not.toBeInTheDocument();
  });

  it("exposes selection through aria-pressed, not colour alone", () => {
    // Queried by the toggle role rather than by name: once selected, the stepper
    // buttons also carry the item name ("Add one …"), which is what makes them
    // usable out of context.
    const { rerender } = renderRow(makeItem());
    expect(screen.getByRole("button", { pressed: false })).toBeInTheDocument();

    rerender(
      <ul>
        <UpsellAddonRow
          item={makeItem()}
          quantity={1}
          onToggle={vi.fn()}
          onQuantityChange={vi.fn()}
        />
      </ul>,
    );
    expect(screen.getByRole("button", { pressed: true })).toBeInTheDocument();
  });

  it("hides the quantity stepper until the row is selected", () => {
    const { rerender } = renderRow(makeItem());
    expect(screen.queryByRole("group")).not.toBeInTheDocument();

    rerender(
      <ul>
        <UpsellAddonRow
          item={makeItem()}
          quantity={2}
          onToggle={vi.fn()}
          onQuantityChange={vi.fn()}
        />
      </ul>,
    );
    expect(screen.getByRole("group", { name: /Quantity for/ })).toBeInTheDocument();
  });

  it("steps the quantity up and down through named controls", async () => {
    const onQuantityChange = vi.fn();
    const user = userEvent.setup();
    renderRow(makeItem(), 2, { onQuantityChange });

    await user.click(screen.getByRole("button", { name: /Add one/ }));
    expect(onQuantityChange).toHaveBeenCalledWith(3);

    await user.click(screen.getByRole("button", { name: /Remove one/ }));
    expect(onQuantityChange).toHaveBeenCalledWith(1);
  });

  it("stops the decrement at one so the row cannot silently deselect itself", () => {
    renderRow(makeItem(), 1);
    expect(screen.getByRole("button", { name: /Remove one/ })).toBeDisabled();
  });
});
