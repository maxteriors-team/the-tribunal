import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FinancingSettingsCard } from "@/components/settings/financing-settings-card";
import type { FinancingConfig, PricingSettings } from "@/types/sales-wizard";

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

function financing(overrides: Partial<FinancingConfig> = {}): FinancingConfig {
  return {
    enabled: true,
    provider: "Wisetack",
    max_amount: 25000,
    terms: [6, 12, 24],
    default_term: 24,
    apr: 0,
    fee_buffer: 0.11,
    category_minimums: { landscape: 0, roofing: 1000 },
    headline: null,
    body: null,
    points: [],
    disclaimer: "Estimates only.",
    ...overrides,
  };
}

function pricing(fin: FinancingConfig): PricingSettings {
  return {
    comparison_years: 5,
    roofline_comparison_enabled: false,
    quote_validity_days: 30,
  quote_expiry_enabled: true,
    financing: fin,
  };
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
});

describe("FinancingSettingsCard", () => {
  it("seeds a row per financed service, sorted by name", async () => {
    getPricingMock.mockResolvedValue(pricing(financing()));

    renderCard();

    expect(await screen.findByLabelText("Service 1 name")).toHaveValue(
      "landscape",
    );
    expect(screen.getByLabelText("Service 1 minimum ($)")).toHaveValue(0);
    expect(screen.getByLabelText("Service 2 name")).toHaveValue("roofing");
    expect(screen.getByLabelText("Service 2 minimum ($)")).toHaveValue(1000);
    expect(screen.getByLabelText("Estimate disclaimer")).toHaveValue(
      "Estimates only.",
    );
  });

  it("adds a core service with a minimum and preserves the margin knobs", async () => {
    getPricingMock.mockResolvedValue(pricing(financing()));
    updatePricingMock.mockResolvedValue(pricing(financing()));

    renderCard();

    await userEvent.click(
      await screen.findByRole("button", { name: /add service/i }),
    );
    await userEvent.type(screen.getByLabelText("Service 3 name"), "siding");
    const minimum = screen.getByLabelText("Service 3 minimum ($)");
    await userEvent.clear(minimum);
    await userEvent.type(minimum, "2500");

    await userEvent.click(
      screen.getByRole("button", { name: /save financing settings/i }),
    );

    await waitFor(() =>
      expect(updatePricingMock).toHaveBeenCalledWith("ws-1", {
        financing: {
          ...financing(),
          category_minimums: { landscape: 0, roofing: 1000, siding: 2500 },
          disclaimer: "Estimates only.",
        },
      }),
    );
    // The gross-up and cash-reversal inputs must ride through untouched.
    const saved = updatePricingMock.mock.calls[0][1].financing as FinancingConfig;
    expect(saved.fee_buffer).toBe(0.11);
    expect(saved.enabled).toBe(true);
    expect(saved.max_amount).toBe(25000);
  });

  it("removing a service stops it offering financing", async () => {
    getPricingMock.mockResolvedValue(pricing(financing()));
    updatePricingMock.mockResolvedValue(pricing(financing()));

    renderCard();

    await userEvent.click(
      await screen.findByRole("button", { name: "Remove service 2" }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: /save financing settings/i }),
    );

    await waitFor(() =>
      expect(updatePricingMock).toHaveBeenCalledWith("ws-1", {
        financing: {
          ...financing(),
          category_minimums: { landscape: 0 },
          disclaimer: "Estimates only.",
        },
      }),
    );
  });

  it("normalizes the service name the way the server does", async () => {
    getPricingMock.mockResolvedValue(
      pricing(financing({ category_minimums: {} })),
    );
    updatePricingMock.mockResolvedValue(pricing(financing()));

    renderCard();

    await userEvent.click(
      await screen.findByRole("button", { name: /add service/i }),
    );
    await userEvent.type(screen.getByLabelText("Service 1 name"), "  Roofing ");

    await userEvent.click(
      screen.getByRole("button", { name: /save financing settings/i }),
    );

    await waitFor(() =>
      expect(updatePricingMock).toHaveBeenCalledWith("ws-1", {
        financing: {
          ...financing(),
          category_minimums: { roofing: 0 },
          disclaimer: "Estimates only.",
        },
      }),
    );
  });

  it("blocks a duplicate service instead of silently dropping one", async () => {
    getPricingMock.mockResolvedValue(pricing(financing()));

    renderCard();

    await userEvent.click(
      await screen.findByRole("button", { name: /add service/i }),
    );
    await userEvent.type(screen.getByLabelText("Service 3 name"), "Roofing");
    await userEvent.click(
      screen.getByRole("button", { name: /save financing settings/i }),
    );

    await waitFor(() => expect(toastError).toHaveBeenCalled());
    expect(updatePricingMock).not.toHaveBeenCalled();
  });

  it("blocks an unnamed service", async () => {
    getPricingMock.mockResolvedValue(pricing(financing()));

    renderCard();

    await userEvent.click(
      await screen.findByRole("button", { name: /add service/i }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: /save financing settings/i }),
    );

    await waitFor(() => expect(toastError).toHaveBeenCalled());
    expect(updatePricingMock).not.toHaveBeenCalled();
  });

  it("saves a blank disclaimer as null so the standard one is used", async () => {
    getPricingMock.mockResolvedValue(pricing(financing()));
    updatePricingMock.mockResolvedValue(pricing(financing()));

    renderCard();

    await userEvent.clear(await screen.findByLabelText("Estimate disclaimer"));
    await userEvent.click(
      screen.getByRole("button", { name: /save financing settings/i }),
    );

    await waitFor(() =>
      expect(updatePricingMock).toHaveBeenCalledWith("ws-1", {
        financing: {
          ...financing(),
          category_minimums: { landscape: 0, roofing: 1000 },
          disclaimer: null,
        },
      }),
    );
  });
});
