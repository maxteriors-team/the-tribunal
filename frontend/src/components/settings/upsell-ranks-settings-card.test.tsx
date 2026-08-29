import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { UpsellRanksSettingsCard } from "@/components/settings/upsell-ranks-settings-card";
import type { PricingSettings, UpsellConfig } from "@/types/sales-wizard";

/**
 * This card writes two numbers that change what a technician can do in the
 * field, so the tests concentrate on the ways a careless save could quietly
 * break selling: a blank limit becoming 0, ranks colliding on a key, and the
 * block-replace save dropping fields the editor never showed.
 */

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

function upsell(overrides: Partial<UpsellConfig> = {}): UpsellConfig {
  return {
    field_proposal_limit: 1500,
    ranks: [
      { key: "bronze", name: "Bronze", threshold: 2000, reward: "$100 bonus" },
      { key: "gold", name: "Gold", threshold: 10000, reward: "$500 bonus" },
    ],
    ...overrides,
  };
}

function pricing(up: UpsellConfig): PricingSettings {
  return {
    comparison_years: 5,
    roofline_comparison_enabled: false,
    quote_validity_days: 30,
  quote_expiry_enabled: true,
    upsell: up,
  };
}

function renderCard() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  render(
    <QueryClientProvider client={client}>
      <UpsellRanksSettingsCard />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  useWorkspaceIdMock.mockReturnValue("ws-1");
});

describe("UpsellRanksSettingsCard", () => {
  it("seeds the limit and a row per configured rank", async () => {
    getPricingMock.mockResolvedValue(pricing(upsell()));

    renderCard();

    expect(await screen.findByLabelText("Lead Technician on-site limit ($)")).toHaveValue(
      1500,
    );
    expect(screen.getByLabelText("Rank 1 name")).toHaveValue("Bronze");
    expect(screen.getByLabelText("Rank 1 target ($)")).toHaveValue(2000);
    expect(screen.getByLabelText("Rank 1 bonus")).toHaveValue("$100 bonus");
    expect(screen.getByLabelText("Rank 2 name")).toHaveValue("Gold");
  });

  it("saves a blank limit as no-limit, never as zero", async () => {
    // A blank field saving as 0 would stop every technician selling anything.
    getPricingMock.mockResolvedValue(pricing(upsell()));
    updatePricingMock.mockResolvedValue(pricing(upsell()));
    const user = userEvent.setup();

    renderCard();
    await user.clear(await screen.findByLabelText("Lead Technician on-site limit ($)"));
    await user.click(screen.getByRole("button", { name: /save field selling/i }));

    await waitFor(() => expect(updatePricingMock).toHaveBeenCalled());
    expect(updatePricingMock.mock.calls[0][1].upsell.field_proposal_limit).toBeNull();
  });

  it("derives a key for a new rank so operators never type one", async () => {
    getPricingMock.mockResolvedValue(pricing(upsell({ ranks: [] })));
    updatePricingMock.mockResolvedValue(pricing(upsell()));
    const user = userEvent.setup();

    renderCard();
    await user.click(await screen.findByRole("button", { name: /add rank/i }));
    await user.type(screen.getByLabelText("Rank 1 name"), "Top Closer");
    await user.clear(screen.getByLabelText("Rank 1 target ($)"));
    await user.type(screen.getByLabelText("Rank 1 target ($)"), "7500");
    await user.type(screen.getByLabelText("Rank 1 bonus"), "$300 bonus");
    await user.click(screen.getByRole("button", { name: /save field selling/i }));

    await waitFor(() => expect(updatePricingMock).toHaveBeenCalled());
    expect(updatePricingMock.mock.calls[0][1].upsell.ranks).toEqual([
      { key: "top-closer", name: "Top Closer", threshold: 7500, reward: "$300 bonus" },
    ]);
  });

  it("refuses two new ranks that would collide on the same derived key", async () => {
    // Both slugify to "gold", which would make two rungs indistinguishable on
    // the technician's scoreboard.
    getPricingMock.mockResolvedValue(pricing(upsell({ ranks: [] })));
    const user = userEvent.setup();

    renderCard();
    const addRank = await screen.findByRole("button", { name: /add rank/i });
    await user.click(addRank);
    await user.click(addRank);
    await user.type(screen.getByLabelText("Rank 1 name"), "Gold");
    await user.type(screen.getByLabelText("Rank 2 name"), "Gold");
    await user.click(screen.getByRole("button", { name: /save field selling/i }));

    expect(toastError).toHaveBeenCalledWith('Two ranks are both called "Gold"');
    expect(updatePricingMock).not.toHaveBeenCalled();
  });

  it("refuses a rank with no name rather than saving a blank rung", async () => {
    getPricingMock.mockResolvedValue(pricing(upsell({ ranks: [] })));
    const user = userEvent.setup();

    renderCard();
    await user.click(await screen.findByRole("button", { name: /add rank/i }));
    await user.click(screen.getByRole("button", { name: /save field selling/i }));

    expect(toastError).toHaveBeenCalledWith(
      "Give every rank a name, or remove the empty row",
    );
    expect(updatePricingMock).not.toHaveBeenCalled();
  });

  it("refuses a negative limit", async () => {
    getPricingMock.mockResolvedValue(pricing(upsell()));
    const user = userEvent.setup();

    renderCard();
    const field = await screen.findByLabelText("Lead Technician on-site limit ($)");
    await user.clear(field);
    await user.type(field, "-5");
    await user.click(screen.getByRole("button", { name: /save field selling/i }));

    expect(toastError).toHaveBeenCalledWith(
      "On-site limit must be a number ≥ 0, or blank for no limit",
    );
    expect(updatePricingMock).not.toHaveBeenCalled();
  });

  it("saves an empty ladder rather than inventing ranks", async () => {
    // No ranks is a supported state: the technician still sees what they sold.
    getPricingMock.mockResolvedValue(pricing(upsell()));
    updatePricingMock.mockResolvedValue(pricing(upsell({ ranks: [] })));
    const user = userEvent.setup();

    renderCard();
    await user.click(await screen.findByRole("button", { name: "Remove rank 1" }));
    await user.click(screen.getByRole("button", { name: "Remove rank 1" }));
    await user.click(screen.getByRole("button", { name: /save field selling/i }));

    await waitFor(() => expect(updatePricingMock).toHaveBeenCalled());
    expect(updatePricingMock.mock.calls[0][1].upsell.ranks).toEqual([]);
  });

  it("blank bonus text saves as null, not an empty string", async () => {
    getPricingMock.mockResolvedValue(
      pricing(upsell({ ranks: [{ key: "gold", name: "Gold", threshold: 100, reward: "x" }] })),
    );
    updatePricingMock.mockResolvedValue(pricing(upsell()));
    const user = userEvent.setup();

    renderCard();
    await user.clear(await screen.findByLabelText("Rank 1 bonus"));
    await user.click(screen.getByRole("button", { name: /save field selling/i }));

    await waitFor(() => expect(updatePricingMock).toHaveBeenCalled());
    expect(updatePricingMock.mock.calls[0][1].upsell.ranks[0].reward).toBeNull();
  });
});
