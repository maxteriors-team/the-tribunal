import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BistroPricingSettingsCard } from "@/components/settings/bistro-pricing-settings-card";
import type { PricingSettings } from "@/types/sales-wizard";

const { getPricingMock, updatePricingMock, listItemsMock, useWorkspaceIdMock, toastError } =
  vi.hoisted(() => ({
    getPricingMock: vi.fn(),
    updatePricingMock: vi.fn(),
    listItemsMock: vi.fn(),
    useWorkspaceIdMock: vi.fn(),
    toastError: vi.fn(),
  }));

vi.mock("@/lib/api/sales-wizard", () => ({
  salesWizardApi: {
    getPricing: getPricingMock,
    updatePricing: updatePricingMock,
  },
}));

vi.mock("@/lib/api/inventory", () => ({
  inventoryApi: { listItems: listItemsMock },
}));
vi.mock("@/hooks/useWorkspaceId", () => ({
  useWorkspaceId: () => useWorkspaceIdMock(),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: toastError },
}));

function pricing(overrides: Record<string, unknown> = {}): PricingSettings {
  return {
    comparison_years: 5,
    roofline_comparison_enabled: false,
    quote_validity_days: 30,
  quote_expiry_enabled: true,
    bistro: {
      enabled: false,
      minimum: 500,
      temporary: {
        label: "Temporary Bistro Lighting",
        lights_per_ft: 10,
        poles_each: 4,
        lights_inventory_sku: "BISTRO-TEMP-200FT",
        poles_inventory_sku: "BISTRO-TEMP-POLE",
        stock_feet_per_light_unit: 200,
      },
      permanent: {
        label: "Permanent Bistro Lighting",
        lights_per_ft: 20,
        poles_each: 6,
        lights_inventory_sku: "BISTRO-PERM-FT",
        poles_inventory_sku: "BISTRO-PERM-POLE",
        stock_feet_per_light_unit: 1,
      },
      tiers: [{ key: "easy", name: "Easy", per_ft: 18, classic_per_ft: 15 }],
      color: { name: "Color Bistro", hardware: 577, strand_lengths: [50] },
      classic: { name: "Classic Bistro", hardware: 35, strand_lengths: [] },
      ...overrides,
    },
  } as unknown as PricingSettings;
}

function renderCard() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  render(
    <QueryClientProvider client={client}>
      <BistroPricingSettingsCard />
    </QueryClientProvider>,
  );
}

async function replace(label: string, value: string) {
  const input = await screen.findByLabelText(label);
  await userEvent.clear(input);
  await userEvent.type(input, value);
}

beforeEach(() => {
  vi.clearAllMocks();
  useWorkspaceIdMock.mockReturnValue("ws-1");
  listItemsMock.mockResolvedValue({
    items: [
      {
        id: "temp-set",
        name: "Temporary Bistro set",
        sku: "BISTRO-TEMP-200FT",
        unit_of_measure: "set",
        is_active: true,
      },
      {
        id: "temp-pole",
        name: "Temporary Bistro pole",
        sku: "BISTRO-TEMP-POLE",
        unit_of_measure: "each",
        is_active: true,
      },
      {
        id: "perm-ft",
        name: "Permanent Bistro footage",
        sku: "BISTRO-PERM-FT",
        unit_of_measure: "ft",
        is_active: true,
      },
      {
        id: "perm-pole",
        name: "Permanent Bistro pole",
        sku: "BISTRO-PERM-POLE",
        unit_of_measure: "each",
        is_active: true,
      },
    ],
    total: 4,
    page: 1,
    page_size: 100,
  });
});

describe("BistroPricingSettingsCard", () => {
  it("shows all measured-run rates and explains the separate permanent calculator", async () => {
    getPricingMock.mockResolvedValue(pricing());

    renderCard();

    expect(await screen.findByLabelText("Temporary lights per foot ($)")).toHaveValue(10);
    expect(screen.getByLabelText("Temporary poles/supports each ($)")).toHaveValue(4);
    expect(screen.getByLabelText("Permanent Bistro lights per foot ($)")).toHaveValue(20);
    expect(screen.getByLabelText("Permanent Bistro poles/supports each ($)")).toHaveValue(6);
    expect(screen.getByLabelText("Feet covered by one temporary set")).toHaveValue(200);
    expect(screen.getByLabelText("Temporary light-set inventory item")).toHaveTextContent(
      "Temporary Bistro set",
    );
    expect(
      screen.getByText(/permanent holiday lighting uses its separate kit-and-COGS/i),
    ).toBeVisible();
    expect(screen.getByText(/financing fees and commission adjustments/i)).toBeVisible();
  });

  it("saves all four rates while preserving legacy Bistro fields", async () => {
    getPricingMock.mockResolvedValue(pricing());
    updatePricingMock.mockResolvedValue(pricing({ enabled: true }));

    renderCard();

    await userEvent.click(await screen.findByRole("switch", { name: "Offer Bistro lighting" }));
    await replace("Temporary lights per foot ($)", "11.5");
    await replace("Temporary poles/supports each ($)", "4.5");
    await replace("Permanent Bistro lights per foot ($)", "22");
    await replace("Permanent Bistro poles/supports each ($)", "7");
    await replace("Bistro job minimum ($)", "750");
    await userEvent.click(screen.getByRole("button", { name: /save Bistro pricing/i }));

    await waitFor(() =>
      expect(updatePricingMock).toHaveBeenCalledWith("ws-1", {
        bistro: {
          enabled: true,
          minimum: 750,
          temporary: {
            label: "Temporary Bistro Lighting",
            lights_per_ft: 11.5,
            poles_each: 4.5,
            lights_inventory_sku: "BISTRO-TEMP-200FT",
            poles_inventory_sku: "BISTRO-TEMP-POLE",
            stock_feet_per_light_unit: 200,
          },
          permanent: {
            label: "Permanent Bistro Lighting",
            lights_per_ft: 22,
            poles_each: 7,
            lights_inventory_sku: "BISTRO-PERM-FT",
            poles_inventory_sku: "BISTRO-PERM-POLE",
            stock_feet_per_light_unit: 1,
          },
          tiers: [{ key: "easy", name: "Easy", per_ft: 18, classic_per_ft: 15 }],
          color: { name: "Color Bistro", hardware: 577, strand_lengths: [50] },
          classic: { name: "Classic Bistro", hardware: 35, strand_lengths: [] },
        },
      }),
    );
  });

  it("blocks an enabled configuration with a zero rate", async () => {
    getPricingMock.mockResolvedValue(pricing({ enabled: true }));

    renderCard();

    await replace("Temporary poles/supports each ($)", "0");
    await userEvent.click(screen.getByRole("button", { name: /save Bistro pricing/i }));

    await waitFor(() =>
      expect(toastError).toHaveBeenCalledWith(
        "Every active Bistro light and pole rate must be greater than 0",
      ),
    );
    expect(updatePricingMock).not.toHaveBeenCalled();
  });
});
