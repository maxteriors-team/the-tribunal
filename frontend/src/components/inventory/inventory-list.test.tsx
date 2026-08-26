import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { InventoryList } from "@/components/inventory/inventory-list";
import { can as roleCan, roleTier, type Capability } from "@/lib/permissions";
import type { InventoryItem, ReorderReport } from "@/types/inventory";

/**
 * Cost scoping and low-stock signalling on the inventory screen.
 *
 * Product rule: the API redacts every money field to `0` below `billing:read`,
 * so the table must omit the cost columns entirely for those tiers — rendering
 * "$0.00" would read as a fact rather than as a hidden value. Quantities stay
 * visible for everyone, because "how much is left on the truck" is exactly the
 * question a field crew opens this screen to answer.
 */

const {
  listItemsMock,
  reorderReportMock,
  listLocationsMock,
  capabilitiesMock,
  workspaceIdMock,
} = vi.hoisted(() => ({
  listItemsMock: vi.fn(),
  reorderReportMock: vi.fn(),
  listLocationsMock: vi.fn(),
  capabilitiesMock: vi.fn(),
  workspaceIdMock: vi.fn(),
}));

vi.mock("@/lib/api/inventory", () => ({
  inventoryApi: {
    listItems: listItemsMock,
    reorderReport: reorderReportMock,
    listLocations: listLocationsMock,
    deleteItem: vi.fn(),
    reorderSuggestion: vi.fn(),
    listLedger: vi.fn(),
  },
}));

vi.mock("@/hooks/useCapabilities", () => ({
  useCapabilities: () => capabilitiesMock(),
}));

vi.mock("@/hooks/useWorkspaceId", () => ({
  useWorkspaceId: () => workspaceIdMock(),
}));

function signedInAs(role: string) {
  capabilitiesMock.mockReturnValue({
    tier: roleTier(role),
    can: (capability: Capability) => roleCan(role, capability),
  });
}

const item: InventoryItem = {
  id: "item-1",
  workspace_id: "ws-1",
  catalog_item_id: null,
  name: "Sodium hypochlorite",
  sku: "SH-125",
  unit_of_measure: "gallon",
  is_active: true,
  valuation_method: "weighted_average",
  reorder_point: 20,
  reorder_quantity: 55,
  safety_stock: 5,
  lead_time_days: 7,
  supplier_name: "Chem Co",
  supplier_sku: null,
  notes: null,
  quantity_on_hand: 8,
  quantity_reserved: 2,
  quantity_deployed: 1,
  available_to_promise: 5,
  total_value: 32,
  avg_unit_cost: 4,
  is_low_stock: true,
  last_movement_at: "2026-08-01T12:00:00.000Z",
  created_at: "2026-07-01T12:00:00.000Z",
  updated_at: "2026-08-01T12:00:00.000Z",
};

const reorderReport: ReorderReport = {
  items: [
    {
      item_id: "item-1",
      item_name: "Sodium hypochlorite",
      sku: "SH-125",
      unit_of_measure: "gallon",
      quantity_on_hand: 8,
      quantity_reserved: 2,
      quantity_deployed: 1,
      available_to_promise: 5,
      reorder_point: 20,
      reorder_quantity: 55,
      safety_stock: 5,
      lead_time_days: 7,
      supplier_name: "Chem Co",
      supplier_sku: null,
      shortfall: 12,
      days_of_cover: 3,
      avg_daily_usage: 2.5,
      suggested_reorder_point: 22.5,
    },
  ],
  total: 1,
  generated_at: "2026-08-03T12:00:00.000Z",
  lookback_days: 90,
};

function renderList() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <InventoryList />
    </QueryClientProvider>,
  );
}

describe("InventoryList", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    workspaceIdMock.mockReturnValue("ws-1");
    listItemsMock.mockResolvedValue({
      items: [item],
      total: 1,
      page: 1,
      page_size: 200,
      pages: 1,
    });
    reorderReportMock.mockResolvedValue(reorderReport);
    listLocationsMock.mockResolvedValue([]);
  });

  it("shows quantities and cost columns for a billing reader", async () => {
    signedInAs("owner");
    renderList();

    expect(await screen.findByText("Sodium hypochlorite")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Owned" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Reserved" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Deployed" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Available" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "5" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Value" })).toBeInTheDocument();
    expect(screen.getByText("$32.00")).toBeInTheDocument();
  });

  it("omits cost columns for the field tier but keeps quantities", async () => {
    signedInAs("technician");
    renderList();

    expect(await screen.findByText("Sodium hypochlorite")).toBeInTheDocument();
    expect(screen.getByText("8")).toBeInTheDocument();
    expect(
      screen.queryByRole("columnheader", { name: "Value" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("columnheader", { name: "Avg cost" }),
    ).not.toBeInTheDocument();
    // Not even a redacted zero: the column is gone, so nothing reads as a price.
    expect(screen.queryByText("$0.00")).not.toBeInTheDocument();
  });

  it("hides stock-changing actions from callers without billing:write", async () => {
    signedInAs("technician");
    renderList();

    await screen.findByText("Sodium hypochlorite");
    expect(
      screen.queryByRole("button", { name: "Track item" }),
    ).not.toBeInTheDocument();
  });

  it("flags low stock and can filter down to just those items", async () => {
    signedInAs("owner");
    const user = userEvent.setup();
    renderList();

    expect(await screen.findByText("Low stock")).toBeInTheDocument();
    expect(
      screen.getByText(/1 item at or below the reorder point/),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Show only these" }));

    await waitFor(() => {
      expect(listItemsMock).toHaveBeenCalledWith(
        "ws-1",
        expect.objectContaining({ low_stock: true }),
      );
    });
  });

  it("renders no banner when nothing is low", async () => {
    signedInAs("owner");
    reorderReportMock.mockResolvedValue({
      ...reorderReport,
      items: [],
      total: 0,
    });
    renderList();

    await screen.findByText("Sodium hypochlorite");
    expect(
      screen.queryByText(/at or below the reorder point/),
    ).not.toBeInTheDocument();
  });
});
