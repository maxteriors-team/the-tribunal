import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PermanentPricingSettingsCard } from "@/components/settings/permanent-pricing-settings-card";
import type { PermanentConfig, PricingSettings } from "@/types/sales-wizard";

const { getPricingMock, updatePricingMock, useWorkspaceIdMock, toastError } =
  vi.hoisted(() => ({
    getPricingMock: vi.fn(),
    updatePricingMock: vi.fn(),
    useWorkspaceIdMock: vi.fn(),
    toastError: vi.fn(),
  }));

vi.mock("@/lib/api/sales-wizard", () => ({
  salesWizardApi: {
    getPricing: getPricingMock,
    updatePricing: updatePricingMock,
  },
}));

vi.mock("@/hooks/useWorkspaceId", () => ({
  useWorkspaceId: () => useWorkspaceIdMock(),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: toastError },
}));

function permanent(overrides: Partial<PermanentConfig> = {}): PermanentConfig {
  return {
    enabled: false,
    label: "Permanent Holiday Lighting",
    easy_markup: 2.5,
    standard_markup: 3,
    complex_markup: 3.5,
    markup: 3.5,
    packages: [
      { feet: 100, cost: 1249 },
      { feet: 150, cost: 1649 },
      { feet: 200, cost: 2099 },
      { feet: 400, cost: 3999 },
    ],
    per_ft: 0,
    controller_base: 299,
    per_channel: 45,
    included_channels: 1,
    minimum: 0,
    perks: ["Pro install"],
    ...overrides,
  };
}

function pricing(perm: PermanentConfig): PricingSettings {
  return {
    comparison_years: 5,
    roofline_comparison_enabled: false,
    quote_validity_days: 30,
  quote_expiry_enabled: true,
    permanent: perm,
  };
}

function renderCard() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  render(
    <QueryClientProvider client={client}>
      <PermanentPricingSettingsCard />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  useWorkspaceIdMock.mockReturnValue("ws-1");
});

describe("PermanentPricingSettingsCard", () => {
  it("seeds the fields from the saved permanent config", async () => {
    getPricingMock.mockResolvedValue(pricing(permanent()));

    renderCard();

    expect(await screen.findByLabelText("Easy multiplier")).toHaveValue(2.5);
    expect(screen.getByLabelText("Standard multiplier")).toHaveValue(3);
    expect(screen.getByLabelText("Complex multiplier")).toHaveValue(3.5);
    expect(screen.getByLabelText("Offering name")).toHaveValue(
      "Permanent Holiday Lighting",
    );
    expect(screen.getAllByLabelText("Kit footage")[0]).toHaveValue(100);
    expect(screen.getAllByLabelText("COGS ($)")[0]).toHaveValue(1249);
  });

  it("saves a complete permanent block, enabling it and preserving perks", async () => {
    getPricingMock.mockResolvedValue(
      pricing(permanent({ enabled: false, perks: ["Pro install"] })),
    );
    updatePricingMock.mockResolvedValue(
      pricing(permanent({ enabled: true, markup: 4 })),
    );

    renderCard();

    const toggle = await screen.findByRole("switch", {
      name: "Offer permanent holiday lighting",
    });
    await userEvent.click(toggle);

    const markup = screen.getByLabelText("Complex multiplier");
    await userEvent.clear(markup);
    await userEvent.type(markup, "4");

    await userEvent.click(
      screen.getByRole("button", { name: /save permanent pricing/i }),
    );

    await waitFor(() =>
      expect(updatePricingMock).toHaveBeenCalledWith("ws-1", {
        permanent: {
          enabled: true,
          label: "Permanent Holiday Lighting",
          easy_markup: 2.5,
          standard_markup: 3,
          complex_markup: 4,
          markup: 4,
          packages: [
            { feet: 100, cost: 1249 },
            { feet: 150, cost: 1649 },
            { feet: 200, cost: 2099 },
            { feet: 400, cost: 3999 },
          ],
          per_ft: 0,
          controller_base: 299,
          per_channel: 45,
          included_channels: 1,
          minimum: 0,
          perks: ["Pro install"],
        },
      }),
    );
  });

  it("blocks save when the offering name is empty", async () => {
    getPricingMock.mockResolvedValue(pricing(permanent()));

    renderCard();

    const label = await screen.findByLabelText("Offering name");
    await userEvent.clear(label);
    await userEvent.click(
      screen.getByRole("button", { name: /save permanent pricing/i }),
    );

    await waitFor(() => expect(toastError).toHaveBeenCalled());
    expect(updatePricingMock).not.toHaveBeenCalled();
  });
});
