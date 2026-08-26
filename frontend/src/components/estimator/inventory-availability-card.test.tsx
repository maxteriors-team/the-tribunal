import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { QuoteInventoryAvailability } from "@/types/inventory";

import { InventoryAvailabilityCard } from "./inventory-availability-card";

const availability: QuoteInventoryAvailability = {
  connected: true,
  is_available: false,
  items: [
    {
      sku: "BISTRO-TEMP-200FT",
      description: "Temporary Bistro sets",
      inventory_behavior: "reusable",
      required_quantity: 2,
      item_id: "item-1",
      item_name: "Temporary Bistro set",
      unit_of_measure: "set",
      tracked: true,
      is_counted: true,
      quantity_on_hand: 3,
      quantity_reserved: 1,
      quantity_deployed: 1,
      available_to_promise: 1,
      shortage_quantity: 1,
      is_available: false,
    },
  ],
};

describe("InventoryAvailabilityCard", () => {
  it("shows owned, reserved, deployed, ATP, and shortage quantities", () => {
    render(<InventoryAvailabilityCard availability={availability} />);

    expect(screen.getByText("1 required item is short.")).toBeVisible();
    expect(screen.getByRole("cell", { name: "2 set" })).toBeVisible();
    expect(screen.getAllByRole("cell", { name: "1" })).toHaveLength(3);
    expect(screen.getByRole("cell", { name: "3" })).toBeVisible();
    expect(screen.getByRole("cell", { name: "1 short" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Open inventory" })).toHaveAttribute(
      "href",
      "/inventory",
    );
  });

  it("distinguishes uncounted and untracked requirements", () => {
    render(
      <InventoryAvailabilityCard
        availability={{
          connected: false,
          is_available: false,
          items: [
            {
              ...availability.items![0]!,
              sku: "XFMR",
              is_counted: false,
              is_available: false,
            },
            {
              ...availability.items![0]!,
              sku: "MISSING",
              tracked: false,
              is_counted: false,
              is_available: false,
            },
          ],
        }}
      />,
    );

    expect(screen.getByText(/not connected to active inventory/i)).toBeVisible();
    expect(screen.getByRole("cell", { name: "Not counted" })).toBeVisible();
    expect(screen.getByRole("cell", { name: "Not tracked" })).toBeVisible();
  });

  it("shows progress while availability is loading", () => {
    render(<InventoryAvailabilityCard availability={undefined} pending />);

    expect(screen.getByText("Checking inventory availability…")).toBeVisible();
  });
});
