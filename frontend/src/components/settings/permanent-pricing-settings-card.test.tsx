import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PermanentPricingSettingsCard } from "@/components/settings/permanent-pricing-settings-card";
import type { PermanentConfig, PricingSettings } from "@/types/sales-wizard";

const { getPricingMock, updatePricingMock, useWorkspaceIdMock, toastError } = vi.hoisted(() => ({
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
    green_sky: {
      enabled: false,
      merchant_number: null,
      plan_number: null,
      term_months: null,
      apr_percent: null,
      offer_details: null,
    },
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
    expect(screen.getByLabelText("Offering name")).toHaveValue("Permanent Holiday Lighting");
    expect(screen.getAllByLabelText("Kit footage")[0]).toHaveValue(100);
    expect(screen.getAllByLabelText("COGS ($)")[0]).toHaveValue(1249);
  });

  it("saves a complete permanent block, enabling it and preserving perks", async () => {
    getPricingMock.mockResolvedValue(
      pricing(permanent({ enabled: false, perks: ["Pro install"] })),
    );
    updatePricingMock.mockResolvedValue(pricing(permanent({ enabled: true, markup: 4 })));

    renderCard();

    const toggle = await screen.findByRole("switch", {
      name: "Offer permanent holiday lighting",
    });
    await userEvent.click(toggle);

    const markup = screen.getByLabelText("Complex multiplier");
    await userEvent.clear(markup);
    await userEvent.type(markup, "4");

    await userEvent.click(screen.getByRole("button", { name: /save permanent pricing/i }));

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
          green_sky: {
            enabled: false,
            merchant_number: null,
            plan_number: null,
            apr_percent: null,
            term_months: null,
            offer_details: null,
          },
        },
      }),
    );
  });

  it("blocks save when the offering name is empty", async () => {
    getPricingMock.mockResolvedValue(pricing(permanent()));

    renderCard();

    const label = await screen.findByLabelText("Offering name");
    await userEvent.clear(label);
    await userEvent.click(screen.getByRole("button", { name: /save permanent pricing/i }));

    await waitFor(() => expect(toastError).toHaveBeenCalled());
    expect(updatePricingMock).not.toHaveBeenCalled();
  });
});

describe("PermanentPricingSettingsCard GreenSky setup", () => {
  it("starts the settled 0% for 24-month program without inventing IDs or copy", async () => {
    getPricingMock.mockResolvedValue(pricing(permanent()));
    const user = userEvent.setup();
    renderCard();

    await user.click(
      await screen.findByRole("switch", {
        name: /enable greensky on new permanent proposals/i,
      }),
    );

    expect(screen.getByLabelText("APR (%)")).toHaveValue(0);
    expect(screen.getByLabelText("Term (months)")).toHaveValue(24);
    expect(screen.getByLabelText("Merchant number")).toHaveValue("");
    expect(screen.getByLabelText("Plan number")).toHaveValue("");
    expect(screen.getByLabelText("Provider-approved offer details")).toHaveValue("");
    expect(screen.getByRole("button", { name: /save permanent pricing/i })).toBeDisabled();
    expect(screen.getByTestId("green-sky-validation")).toHaveTextContent(
      "Enter the GreenSky merchant number.",
    );
  });

  it("saves a complete GreenSky program", async () => {
    getPricingMock.mockResolvedValue(pricing(permanent()));
    updatePricingMock.mockResolvedValue(pricing(permanent()));
    const user = userEvent.setup();
    renderCard();

    await user.click(
      await screen.findByRole("switch", {
        name: /enable greensky on new permanent proposals/i,
      }),
    );
    await user.type(screen.getByLabelText("Merchant number"), "1234567890");
    await user.type(screen.getByLabelText("Plan number"), "246810");
    await user.type(
      screen.getByLabelText("Provider-approved offer details"),
      "Provider-approved 0% APR for 24 months.",
    );

    expect(screen.getByTestId("green-sky-validation")).toHaveTextContent(
      "GreenSky setup is complete: 0% APR for 24 months.",
    );
    await user.click(screen.getByRole("button", { name: /save permanent pricing/i }));

    await waitFor(() =>
      expect(updatePricingMock).toHaveBeenCalledWith("ws-1", {
        permanent: expect.objectContaining({
          green_sky: {
            enabled: true,
            merchant_number: "1234567890",
            plan_number: "246810",
            apr_percent: 0,
            term_months: 24,
            offer_details: "Provider-approved 0% APR for 24 months.",
          },
        }),
      }),
    );
  });

  it("shows fee, approved-copy, and direct-application safeguards", async () => {
    getPricingMock.mockResolvedValue(
      pricing(
        permanent({
          green_sky: {
            enabled: true,
            merchant_number: "1234567890",
            plan_number: "246810",
            apr_percent: 0,
            term_months: 24,
            offer_details: "Provider-approved fixture copy.",
          },
        }),
      ),
    );
    renderCard();

    expect(
      await screen.findByText(/Maxteriors absorbs GreenSky's 15.25% merchant fee/i),
    ).toBeVisible();
    expect(screen.getByText(/Never add that fee to the borrower's price/i)).toBeVisible();
    expect(screen.getByText(/submit financial information directly to GreenSky/i)).toBeVisible();
    expect(screen.getByText(/Tribunal does not receive or infer/i)).toBeVisible();
    expect(screen.getByText(/Use only GreenSky-approved program language/i)).toBeVisible();
  });
});
