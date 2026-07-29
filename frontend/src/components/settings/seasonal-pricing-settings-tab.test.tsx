import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SeasonalPricingSettingsTab } from "@/components/settings/seasonal-pricing-settings-tab";
import type { PricingSettings } from "@/types/sales-wizard";

const { getPricingMock, updatePricingMock, useWorkspaceIdMock } = vi.hoisted(
  () => ({
    getPricingMock: vi.fn(),
    updatePricingMock: vi.fn(),
    useWorkspaceIdMock: vi.fn(),
  }),
);

vi.mock("@/lib/api/sales-wizard", () => ({
  salesWizardApi: {
    getPricing: getPricingMock,
    updatePricing: updatePricingMock,
  },
}));

vi.mock("@/hooks/useWorkspaceId", () => ({
  useWorkspaceId: () => useWorkspaceIdMock(),
}));

// A workspace exactly as it exists today: seasonal config, and no
// `service_packages` key at all (the block postdates every saved blob).
function pricing(overrides: Partial<PricingSettings> = {}) {
  return {
    christmas: {
      enabled: true,
      roofline_per_ft: 6,
      items: [
        {
          key: "trees",
          label: "Trees",
          unit: "each",
          options: [{ key: "medium", name: "Medium tree", price: 260 }],
        },
      ],
      packages_enabled: true,
      package_order: ["middle"],
      packages: [
        {
          key: "middle",
          label: "Middle — Roofline + Trees",
          name: "The Classic",
          marker: "◆",
          experience: "The complete outline.",
          points: ["Full roofline outlined"],
          includes_roofline: true,
          item_keys: ["trees"],
        },
      ],
    },
    roofline_comparison_enabled: false,
    ...overrides,
  } as unknown as PricingSettings;
}

function renderTab() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <SeasonalPricingSettingsTab />
    </QueryClientProvider>,
  );
}

describe("Pricing tab category selector", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useWorkspaceIdMock.mockReturnValue("ws-1");
    getPricingMock.mockResolvedValue(pricing());
    updatePricingMock.mockImplementation(async () => pricing());
  });

  it("opens on the seasonal set, unchanged for an existing workspace", async () => {
    renderTab();

    expect(await screen.findByText("Seasonal Decor Pricing")).toBeInTheDocument();
    expect(screen.getByText("Christmas Packages")).toBeInTheDocument();
    expect(screen.getByDisplayValue("The Classic")).toBeInTheDocument();
    // A workspace with no service categories is offered exactly one option.
    expect(screen.getByText("Christmas Lighting (seasonal)")).toBeInTheDocument();
  });

  it("switches to a new service category and back without losing edits", async () => {
    const user = userEvent.setup();
    renderTab();
    await screen.findByText("Seasonal Decor Pricing");

    await user.click(screen.getByRole("button", { name: /Add service/i }));

    // The selector switched to the new category and the seasonal editor is gone.
    const nameInput = await screen.findByLabelText("Service name");
    expect(screen.queryByText("Seasonal Decor Pricing")).not.toBeInTheDocument();
    await user.type(nameInput, "Roof Replacement");

    // Back to seasonal, then forward again: the typed name survived.
    await user.click(screen.getByRole("combobox", { name: /Service/i }));
    await user.click(
      await screen.findByRole("option", { name: /Christmas Lighting/i }),
    );
    expect(await screen.findByText("Seasonal Decor Pricing")).toBeInTheDocument();

    await user.click(screen.getByRole("combobox", { name: /Service/i }));
    await user.click(await screen.findByRole("option", { name: "Roof Replacement" }));
    expect(await screen.findByLabelText("Service name")).toHaveValue(
      "Roof Replacement",
    );
  });

  it("starts a new category as three tiers with the middle one steered", async () => {
    const user = userEvent.setup();
    renderTab();
    await screen.findByText("Seasonal Decor Pricing");

    await user.click(screen.getByRole("button", { name: /Add service/i }));
    await screen.findByLabelText("Service name");

    expect(screen.getByDisplayValue("Good")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Better")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Best")).toBeInTheDocument();

    // Exactly one Recommended badge in the customer preview, on the middle tier
    // — the steered middle option the whole three-tier lever depends on.
    const badges = document.querySelectorAll(".cmp-card-tag");
    expect(badges).toHaveLength(1);
    expect(badges[0]).toHaveTextContent("Recommended");
    const steered = badges[0].closest(".cmp-pkg");
    expect(within(steered as HTMLElement).getByText("Preferred")).toBeInTheDocument();
  });

  it("saves the seasonal block and the service list together", async () => {
    const user = userEvent.setup();
    renderTab();
    await screen.findByText("Seasonal Decor Pricing");

    await user.click(screen.getByRole("button", { name: /Add service/i }));
    await user.type(await screen.findByLabelText("Service name"), "Gutters");
    await user.click(screen.getByRole("button", { name: /Save pricing/i }));

    await waitFor(() => expect(updatePricingMock).toHaveBeenCalledTimes(1));
    const body = updatePricingMock.mock.calls[0][1];

    // The seasonal block round-trips untouched…
    expect(body.christmas.packages).toHaveLength(1);
    expect(body.christmas.packages[0].key).toBe("middle");
    expect(body.christmas.roofline_per_ft).toBe(6);
    // …and the new category is saved with a slugged key and a steered middle.
    expect(body.service_packages).toHaveLength(1);
    expect(body.service_packages[0].service_category).toBe("gutters");
    expect(body.service_packages[0].package_order).toEqual([
      "good",
      "better",
      "best",
    ]);
    expect(
      body.service_packages[0].packages.filter(
        (p: { recommended: boolean }) => p.recommended,
      ),
    ).toHaveLength(1);
  });

  it("refuses to save a service category with no name", async () => {
    const user = userEvent.setup();
    renderTab();
    await screen.findByText("Seasonal Decor Pricing");

    await user.click(screen.getByRole("button", { name: /Add service/i }));
    await screen.findByLabelText("Service name");
    await user.click(screen.getByRole("button", { name: /Save pricing/i }));

    await waitFor(() => expect(updatePricingMock).not.toHaveBeenCalled());
  });

  it("keeps sending service_packages the server already had", async () => {
    getPricingMock.mockResolvedValue(
      pricing({
        service_packages: [
          {
            service_category: "roof",
            label: "Roof Replacement",
            enabled: true,
            basis: "per_unit",
            unit_label: "squares",
            minimum: 0,
            perks: [],
            inclusions: [],
            package_order: ["good"],
            packages: [
              {
                key: "good",
                label: "Good",
                base_price: 0,
                per_unit_price: 400,
                popular: false,
                recommended: false,
              },
            ],
          },
        ],
      } as unknown as Partial<PricingSettings>),
    );
    const user = userEvent.setup();
    renderTab();
    await screen.findByText("Seasonal Decor Pricing");

    await user.click(screen.getByRole("button", { name: /Save pricing/i }));

    await waitFor(() => expect(updatePricingMock).toHaveBeenCalledTimes(1));
    const body = updatePricingMock.mock.calls[0][1];
    // Saved from the seasonal screen, yet the untouched roof category survives
    // with its frozen key — the endpoint replaces the whole block.
    expect(body.service_packages).toHaveLength(1);
    expect(body.service_packages[0].service_category).toBe("roof");
    expect(body.service_packages[0].packages[0].per_unit_price).toBe(400);
  });
});
