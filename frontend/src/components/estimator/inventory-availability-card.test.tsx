import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { InventoryAvailabilityCard } from "./inventory-availability-card";

describe("InventoryAvailabilityCard", () => {
  it("shows shortages with required, on-hand, and shortfall quantities", () => {
    render(
      <InventoryAvailabilityCard
        availability={{
          has_requirements: true,
          has_shortages: true,
          shortage_items: 1,
          not_counted_items: 0,
          untracked_items: 0,
          items: [
            {
              sku: "PATH",
              inventory_item_name: "Path light",
              required_quantity: 5,
              quantity_on_hand: 2,
              shortfall: 3,
              unit_of_measure: "each",
              status: "shortage",
            },
          ],
        }}
      />,
    );

    expect(screen.getByText("1 required item is short.")).toBeVisible();
    expect(screen.getByRole("cell", { name: "5 each" })).toBeVisible();
    expect(screen.getByRole("cell", { name: "2" })).toBeVisible();
    expect(screen.getByRole("cell", { name: "Short (3 short)" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Open inventory" })).toHaveAttribute(
      "href",
      "/inventory",
    );
  });

  it("distinguishes uncounted and untracked requirements from confirmed shortages", () => {
    render(
      <InventoryAvailabilityCard
        availability={{
          has_requirements: true,
          has_shortages: false,
          shortage_items: 0,
          not_counted_items: 1,
          untracked_items: 1,
          items: [
            {
              sku: "XFMR",
              inventory_item_name: "Transformer",
              required_quantity: 1,
              status: "not_counted",
            },
            {
              sku: "MISSING",
              description: "Unlinked part",
              required_quantity: 1,
              status: "untracked",
            },
          ],
        }}
      />,
    );

    expect(screen.getByText(/need an opening count or inventory link/i)).toBeVisible();
    expect(screen.getByRole("cell", { name: "Not counted" })).toBeVisible();
    expect(screen.getByRole("cell", { name: "Not tracked" })).toBeVisible();
  });

  it("does not claim coverage when a package has no component SKUs", () => {
    render(
      <InventoryAvailabilityCard
        availability={{
          has_requirements: false,
          has_shortages: false,
          shortage_items: 0,
          not_counted_items: 0,
          untracked_items: 0,
          items: [],
        }}
      />,
    );

    expect(screen.getByText(/no inventory component SKUs configured/i)).toBeVisible();
    expect(screen.getByText(/before relying on stock availability/i)).toBeVisible();
  });
});
