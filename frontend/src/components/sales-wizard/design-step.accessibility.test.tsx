import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DesignStep } from "./design-step";
import type { UseSalesWizardReturn } from "./use-sales-wizard";

function wizardFixture(overrides: Partial<UseSalesWizardReturn> = {}): UseSalesWizardReturn {
  return {
    pricing: {
      tiers: [
        {
          key: "good",
          label: "Good",
          name: "Good",
          sections: [{ title: "Fixtures", item_ids: ["roofline"] }],
        },
      ],
      tier_order: ["good"],
    },
    document: { tiers: [] },
    activeTier: "good",
    setActiveTier: vi.fn(),
    quantities: { roofline: 2 },
    setQty: vi.fn(),
    changeQty: vi.fn(),
    charges: [],
    setCharge: vi.fn(),
    addCharge: vi.fn(),
    removeCharge: vi.fn(),
    tierConfig: () => ({ key: "good", label: "Good", name: "Good", sections: [] }),
    lineFor: () => ({ name: "Roofline lights", unit_price: 10, line_total: 20 }),
    catalog: [],
    ...overrides,
  } as unknown as UseSalesWizardReturn;
}

describe("DesignStep quantity controls", () => {
  it("names every control and supports keyboard activation", async () => {
    const user = userEvent.setup();
    const changeQty = vi.fn();
    const setQty = vi.fn();
    render(<DesignStep wizard={wizardFixture({ changeQty, setQty })} />);

    const decrease = screen.getByRole("button", {
      name: "Decrease Roofline lights quantity",
    });
    const quantity = screen.getByRole("spinbutton", {
      name: "Roofline lights quantity",
    });
    const increase = screen.getByRole("button", {
      name: "Increase Roofline lights quantity",
    });

    decrease.focus();
    await user.keyboard("{Enter}");
    expect(changeQty).toHaveBeenCalledWith("roofline", -1);

    increase.focus();
    await user.keyboard(" ");
    expect(changeQty).toHaveBeenCalledWith("roofline", 1);

    fireEvent.change(quantity, { target: { value: "4" } });
    expect(setQty).toHaveBeenLastCalledWith("roofline", 4);
  });

  it("disables decrement at zero without hiding its accessible name", () => {
    render(<DesignStep wizard={wizardFixture({ quantities: { roofline: 0 } })} />);

    expect(
      screen.getByRole("button", { name: "Decrease Roofline lights quantity" }),
    ).toBeDisabled();
  });
});
