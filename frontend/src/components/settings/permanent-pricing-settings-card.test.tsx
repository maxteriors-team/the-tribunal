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
    per_ft: 32,
    controller_base: 299,
    per_channel: 45,
    included_channels: 1,
    minimum: 0,
    perks: ["Pro install"],
    ...overrides,
  };
}

function pricing(perm: PermanentConfig): PricingSettings {
  return { comparison_years: 5, permanent: perm };
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
    getPricingMock.mockResolvedValue(pricing(permanent({ per_ft: 32 })));

    renderCard();

    expect(await screen.findByLabelText("Price per linear foot ($)")).toHaveValue(
      32,
    );
    expect(screen.getByLabelText("Offering name")).toHaveValue(
      "Permanent Holiday Lighting",
    );
    expect(screen.getByLabelText("Controller base price ($)")).toHaveValue(299);
  });

  it("saves a complete permanent block, enabling it and preserving perks", async () => {
    getPricingMock.mockResolvedValue(
      pricing(permanent({ enabled: false, per_ft: 32, perks: ["Pro install"] })),
    );
    updatePricingMock.mockResolvedValue(
      pricing(permanent({ enabled: true, per_ft: 40 })),
    );

    renderCard();

    const toggle = await screen.findByRole("switch", {
      name: "Offer permanent holiday lighting",
    });
    await userEvent.click(toggle);

    const perFt = screen.getByLabelText("Price per linear foot ($)");
    await userEvent.clear(perFt);
    await userEvent.type(perFt, "40");

    await userEvent.click(
      screen.getByRole("button", { name: /save permanent pricing/i }),
    );

    await waitFor(() =>
      expect(updatePricingMock).toHaveBeenCalledWith("ws-1", {
        permanent: {
          enabled: true,
          label: "Permanent Holiday Lighting",
          per_ft: 40,
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
