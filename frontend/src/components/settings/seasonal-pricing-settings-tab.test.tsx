import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SeasonalPricingSettingsTab } from "@/components/settings/seasonal-pricing-settings-tab";
import type {
  ChristmasConfig,
  ChristmasPackage,
  PricingSettings,
  SeasonalItem,
} from "@/types/sales-wizard";

/**
 * Seasonal (Christmas) pricing settings.
 *
 * The offering-level fields matter twice over: `enabled` is what makes Christmas
 * sellable at all, and the season anchors are what the approval flow turns into
 * install/takedown Service Plans. The save is a whole-block replace, so the other
 * half of this suite is proving the fields the editor doesn't expose (`perks`,
 * package markers) round-trip untouched.
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

function seasonalItem(): SeasonalItem {
  return {
    key: "trees",
    label: "Trees",
    unit: "each",
    options: [{ key: "small", name: "Small tree (6–10 ft)", price: 120 }],
  };
}

/** Every package sub-field set, so a save has something to preserve. */
function seasonalPackage(): ChristmasPackage {
  return {
    key: "premier",
    label: "Premier — The Full Display",
    name: "The Premier",
    marker: "★",
    card_tier: "Best",
    experience: "The whole property, transformed.",
    warranty: "Season-long service",
    points: ["Everything, fully dressed"],
    value_tag: "★ The Full Display",
    popular: true,
    includes_roofline: true,
    item_keys: ["trees"],
  };
}

function christmas(overrides: Partial<ChristmasConfig> = {}): ChristmasConfig {
  return {
    enabled: false,
    label: "Christmas Lighting",
    roofline_per_ft: 6,
    items: [seasonalItem()],
    takedown_enabled: true,
    takedown_rate: 0.25,
    storage_price: 0,
    season_install_month: 11,
    season_install_day: 15,
    season_takedown_month: 1,
    season_takedown_day: 8,
    maintenance_through_month: 12,
    maintenance_through_day: 23,
    minimum: 0,
    perks: ["We hang it, we take it down"],
    value_props: [
      { title: "A Worry-Free Christmas", body: "Maintenance through Dec 23." },
    ],
    packages_enabled: false,
    package_order: ["premier"],
    packages: [seasonalPackage()],
    ...overrides,
  };
}

function pricing(xmas: ChristmasConfig): PricingSettings {
  return {
    comparison_years: 5,
    roofline_comparison_enabled: false,
    quote_validity_days: 30,
    christmas: xmas,
  };
}

function renderTab() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  render(
    <QueryClientProvider client={client}>
      <SeasonalPricingSettingsTab />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  useWorkspaceIdMock.mockReturnValue("ws-1");
});

describe("SeasonalPricingSettingsTab", () => {
  it("seeds the offering, takedown, storage, and season controls from the saved config", async () => {
    getPricingMock.mockResolvedValue(
      pricing(
        christmas({
          enabled: true,
          label: "Holiday Lighting",
          takedown_enabled: true,
          takedown_rate: 0.3,
          storage_price: 75,
          minimum: 850,
          season_install_month: 10,
          season_install_day: 20,
          season_takedown_month: 2,
          season_takedown_day: 3,
        }),
      ),
    );

    renderTab();

    expect(
      await screen.findByRole("switch", { name: "Offer Christmas lighting" }),
    ).toBeChecked();
    expect(screen.getByLabelText("Offering name")).toHaveValue(
      "Holiday Lighting",
    );
    expect(screen.getByLabelText("Job minimum ($)")).toHaveValue(850);
    expect(
      screen.getByRole("switch", { name: "Offer post-season takedown" }),
    ).toBeChecked();
    // Stored as a 0..1 fraction, shown to the operator as a percent.
    expect(screen.getByLabelText("Takedown rate (% of install)")).toHaveValue(
      30,
    );
    expect(screen.getByLabelText("Off-season storage price ($)")).toHaveValue(
      75,
    );
    expect(
      screen.getByRole("combobox", { name: "Install month" }),
    ).toHaveTextContent("October");
    expect(screen.getByLabelText("Install day")).toHaveValue(20);
    expect(
      screen.getByRole("combobox", { name: "Takedown month" }),
    ).toHaveTextContent("February");
    expect(screen.getByLabelText("Takedown day")).toHaveValue(3);
  });

  it("saves the edited offering fields and preserves everything it doesn't expose", async () => {
    getPricingMock.mockResolvedValue(pricing(christmas()));
    updatePricingMock.mockResolvedValue(pricing(christmas({ enabled: true })));

    // This case drives seven controls. The default inter-keystroke delay makes
    // it the slowest test in the file and flaky under a loaded full-suite run,
    // so drive it through a delay-free session: still real user events, just
    // without the artificial typing pauses.
    const user = userEvent.setup({ delay: null });
    renderTab();

    await user.click(
      await screen.findByRole("switch", { name: "Offer Christmas lighting" }),
    );

    const label = screen.getByLabelText("Offering name");
    await user.clear(label);
    await user.type(label, "Holiday Lighting");

    const minimum = screen.getByLabelText("Job minimum ($)");
    await user.clear(minimum);
    await user.type(minimum, "850");

    const rate = screen.getByLabelText("Takedown rate (% of install)");
    await user.clear(rate);
    await user.type(rate, "40");

    const storage = screen.getByLabelText("Off-season storage price ($)");
    await user.clear(storage);
    await user.type(storage, "75");

    await user.click(screen.getByRole("combobox", { name: "Install month" }));
    await user.click(await screen.findByRole("option", { name: "October" }));

    const installDay = screen.getByLabelText("Install day");
    await user.clear(installDay);
    await user.type(installDay, "20");

    await user.click(
      screen.getByRole("button", { name: /save seasonal pricing/i }),
    );

    await waitFor(() =>
      expect(updatePricingMock).toHaveBeenCalledWith("ws-1", {
        christmas: {
          enabled: true,
          label: "Holiday Lighting",
          roofline_per_ft: 6,
          minimum: 850,
          takedown_enabled: true,
          // 40% typed by the operator is stored as the 0.4 fraction.
          takedown_rate: 0.4,
          storage_price: 75,
          season_install_month: 10,
          season_install_day: 20,
          season_takedown_month: 1,
          season_takedown_day: 8,
          items: [seasonalItem()],
          // Untouched by this editor — must survive the block-replace save.
          perks: ["We hang it, we take it down"],
          // Likewise: losing these silently rewrites the promises (and the
          // maintenance date) printed on every future client proposal.
          maintenance_through_month: 12,
          maintenance_through_day: 23,
          value_props: [
            {
              title: "A Worry-Free Christmas",
              body: "Maintenance through Dec 23.",
            },
          ],
          packages_enabled: false,
          package_order: ["premier"],
          packages: [seasonalPackage()],
        },
        roofline_comparison_enabled: false,
      }),
    );
  });

  it("turns the offering off and stops selling takedown", async () => {
    getPricingMock.mockResolvedValue(
      pricing(christmas({ enabled: true, takedown_enabled: true })),
    );
    updatePricingMock.mockResolvedValue(pricing(christmas()));

    renderTab();

    await userEvent.click(
      await screen.findByRole("switch", { name: "Offer Christmas lighting" }),
    );
    await userEvent.click(
      screen.getByRole("switch", { name: "Offer post-season takedown" }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: /save seasonal pricing/i }),
    );

    await waitFor(() => expect(updatePricingMock).toHaveBeenCalled());
    expect(updatePricingMock.mock.calls[0][1].christmas).toMatchObject({
      enabled: false,
      takedown_enabled: false,
    });
  });

  it("clamps a season day to one the chosen month actually has", async () => {
    getPricingMock.mockResolvedValue(
      pricing(
        christmas({ season_install_month: 11, season_takedown_month: 1 }),
      ),
    );
    updatePricingMock.mockResolvedValue(pricing(christmas()));

    renderTab();

    // November has 30 days: typing 31 snaps to 30 instead of letting the backend
    // rewrite it after the save.
    const installDay = await screen.findByLabelText("Install day");
    await userEvent.clear(installDay);
    await userEvent.type(installDay, "31");
    expect(installDay).toHaveValue(30);

    // January holds the 31st, but switching to February clamps it to 28 —
    // matching the backend's non-leap clamp.
    const takedownDay = screen.getByLabelText("Takedown day");
    await userEvent.clear(takedownDay);
    await userEvent.type(takedownDay, "31");
    expect(takedownDay).toHaveValue(31);

    await userEvent.click(
      screen.getByRole("combobox", { name: "Takedown month" }),
    );
    await userEvent.click(
      await screen.findByRole("option", { name: "February" }),
    );
    expect(takedownDay).toHaveValue(28);

    await userEvent.click(
      screen.getByRole("button", { name: /save seasonal pricing/i }),
    );

    await waitFor(() => expect(updatePricingMock).toHaveBeenCalled());
    expect(updatePricingMock.mock.calls[0][1].christmas).toMatchObject({
      season_install_month: 11,
      season_install_day: 30,
      season_takedown_month: 2,
      season_takedown_day: 28,
    });
  });

  it("blocks save when the offering name is empty", async () => {
    getPricingMock.mockResolvedValue(pricing(christmas()));

    renderTab();

    const label = await screen.findByLabelText("Offering name");
    await userEvent.clear(label);
    await userEvent.click(
      screen.getByRole("button", { name: /save seasonal pricing/i }),
    );

    await waitFor(() => expect(toastError).toHaveBeenCalled());
    expect(updatePricingMock).not.toHaveBeenCalled();
  });

  it("blocks save when the takedown rate is not a percent", async () => {
    getPricingMock.mockResolvedValue(pricing(christmas()));

    renderTab();

    const rate = await screen.findByLabelText("Takedown rate (% of install)");
    await userEvent.clear(rate);
    await userEvent.type(rate, "125");
    await userEvent.click(
      screen.getByRole("button", { name: /save seasonal pricing/i }),
    );

    await waitFor(() => expect(toastError).toHaveBeenCalled());
    expect(updatePricingMock).not.toHaveBeenCalled();
  });
});
