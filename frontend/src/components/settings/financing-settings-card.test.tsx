import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FinancingSettingsCard } from "@/components/settings/financing-settings-card";
import type { PricingSettings } from "@/types/sales-wizard";

const { getPricingMock, updatePricingMock, useWorkspaceIdMock, toastError } = vi.hoisted(() => ({
  getPricingMock: vi.fn(),
  updatePricingMock: vi.fn(),
  useWorkspaceIdMock: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock("@/lib/api/sales-wizard", () => ({
  salesWizardApi: { getPricing: getPricingMock, updatePricing: updatePricingMock },
}));

vi.mock("@/hooks/useWorkspaceId", () => ({
  useWorkspaceId: () => useWorkspaceIdMock(),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: toastError },
}));

const permanent = {
  enabled: true,
  packages: [],
  easy_markup: 2.5,
  standard_markup: 3,
  complex_markup: 3.5,
  markup: 3.5,
  per_ft: 0,
  controller_base: 0,
  per_channel: 0,
  included_channels: 0,
  minimum: 0,
  label: "Permanent Holiday Lighting",
  perks: [],
  financing: {
    provider: "GreenSky" as const,
    plan_number: "6124",
    apr: 0,
    term_months: 24,
    merchant_fee_rate: 0.1525,
    sales_commission_rate: 0.07,
  },
};

function pricing(): PricingSettings {
  return {
    comparison_years: 5,
    roofline_comparison_enabled: false,
    quote_validity_days: 30,
    quote_expiry_enabled: true,
    permanent,
    financing: {
      enabled: true,
      provider: "Legacy provider",
      max_amount: 99999,
      terms: [12],
      default_term: 12,
      apr: 0,
      fee_buffer: 0.5,
      category_minimums: { landscape: 0 },
      points: [],
    },
  } as unknown as PricingSettings;
}

function renderCard() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  render(
    <QueryClientProvider client={client}>
      <FinancingSettingsCard />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  useWorkspaceIdMock.mockReturnValue("ws-1");
  getPricingMock.mockResolvedValue(pricing());
  updatePricingMock.mockResolvedValue(pricing());
});

describe("FinancingSettingsCard", () => {
  it("loads nested Permanent settings and explains the one-price policy", async () => {
    renderCard();

    expect(await screen.findByLabelText("Plan number")).toHaveValue("6124");
    expect(screen.getByLabelText("Financing term (months)")).toHaveValue(24);
    expect(screen.getByLabelText("APR (%)")).toHaveValue(0);
    expect(screen.getByLabelText("Merchant fee (%)")).toHaveValue(15.25);
    expect(screen.getByLabelText("Sales commission (%)")).toHaveValue(7);
    expect(screen.getByText(/merchant fee is a company cost/i)).toBeInTheDocument();
    expect(screen.getByText(/only on exact Permanent Lighting proposals/i)).toBeInTheDocument();
    expect(screen.queryByText(/landscape/i)).not.toBeInTheDocument();
  });

  it("saves converted percentages inside the full Permanent block", async () => {
    renderCard();
    const user = userEvent.setup();

    const values: Array<[string, string]> = [
      ["Plan number", "7000"],
      ["Financing term (months)", "36"],
      ["APR (%)", "5.5"],
      ["Merchant fee (%)", "14"],
      ["Sales commission (%)", "8"],
    ];
    for (const [label, value] of values) {
      const input = await screen.findByLabelText(label);
      await user.clear(input);
      await user.type(input, value);
    }
    await user.click(screen.getByRole("button", { name: /save GreenSky settings/i }));

    await waitFor(() =>
      expect(updatePricingMock).toHaveBeenCalledWith("ws-1", {
        permanent: {
          ...permanent,
          financing: {
            provider: "GreenSky",
            plan_number: "7000",
            apr: 0.055,
            term_months: 36,
            merchant_fee_rate: 0.14,
            sales_commission_rate: 0.08,
          },
        },
      }),
    );
  });

  it("rejects a nonnumeric plan number", async () => {
    renderCard();
    const user = userEvent.setup();
    const input = await screen.findByLabelText("Plan number");
    await user.clear(input);
    await user.type(input, "plan ABC");
    await user.click(screen.getByRole("button", { name: /save GreenSky settings/i }));

    expect(toastError).toHaveBeenCalledWith("Plan number must contain 1–32 digits");
    expect(updatePricingMock).not.toHaveBeenCalled();
  });

  it("rejects an out-of-range percentage", async () => {
    renderCard();
    const user = userEvent.setup();
    const input = await screen.findByLabelText("Merchant fee (%)");
    await user.clear(input);
    await user.type(input, "100");
    await user.click(screen.getByRole("button", { name: /save GreenSky settings/i }));

    expect(toastError).toHaveBeenCalledWith("Merchant fee must be between 0% and less than 100%");
    expect(updatePricingMock).not.toHaveBeenCalled();
  });
});
