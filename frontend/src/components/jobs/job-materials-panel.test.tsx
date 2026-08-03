import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { JobMaterialsPanel } from "@/components/jobs/job-materials-panel";
import { can as roleCan, roleTier, type Capability } from "@/lib/permissions";
import type { JobMaterials } from "@/types/inventory";

/**
 * Materials on a job.
 *
 * Two product rules are asserted here: costs are hidden below `billing:read`
 * (a technician sees what they used, not what it cost), and removing a line
 * *returns stock* rather than deleting the record — the request that fires is
 * the compensating one.
 */

const {
  listJobMaterialsMock,
  listItemsMock,
  addJobMaterialMock,
  removeJobMaterialMock,
  capabilitiesMock,
} = vi.hoisted(() => ({
  listJobMaterialsMock: vi.fn(),
  listItemsMock: vi.fn(),
  addJobMaterialMock: vi.fn(),
  removeJobMaterialMock: vi.fn(),
  capabilitiesMock: vi.fn(),
}));

vi.mock("@/lib/api/inventory", () => ({
  inventoryApi: {
    listJobMaterials: listJobMaterialsMock,
    listItems: listItemsMock,
    addJobMaterial: addJobMaterialMock,
    removeJobMaterial: removeJobMaterialMock,
  },
}));

vi.mock("@/hooks/useCapabilities", () => ({
  useCapabilities: () => capabilitiesMock(),
}));

function signedInAs(role: string) {
  capabilitiesMock.mockReturnValue({
    tier: roleTier(role),
    can: (capability: Capability) => roleCan(role, capability),
  });
}

const materials: JobMaterials = {
  job_id: "job-1",
  items: [
    {
      id: "entry-1",
      item_id: "item-1",
      item_name: "Sodium hypochlorite",
      location_id: "loc-1",
      location_name: "Truck 1",
      quantity_delta: -3,
      unit_cost: 4,
      value_delta: -12,
      reason: "job_usage",
      reference_type: "job",
      reference_id: "job-1",
      occurred_at: "2026-08-01T12:00:00.000Z",
      note: null,
      quantity_after: 5,
      value_after: 20,
      unit_cost_after: 4,
      created_at: "2026-08-01T12:00:00.000Z",
    },
  ],
  total_material_cost: 12,
};

function renderPanel(readOnly = false) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <JobMaterialsPanel workspaceId="ws-1" jobId="job-1" readOnly={readOnly} />
    </QueryClientProvider>,
  );
}

describe("JobMaterialsPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listJobMaterialsMock.mockResolvedValue(materials);
    listItemsMock.mockResolvedValue({
      items: [
        {
          id: "item-1",
          name: "Sodium hypochlorite",
          unit_of_measure: "gallon",
          quantity_on_hand: 5,
        },
      ],
      total: 1,
      page: 1,
      page_size: 200,
      pages: 1,
    });
    removeJobMaterialMock.mockResolvedValue({});
  });

  it("shows the material and its cost to a billing reader", async () => {
    signedInAs("owner");
    renderPanel();

    expect(await screen.findByText("Sodium hypochlorite")).toBeInTheDocument();
    // Once as the panel total, once on the line it came from.
    expect(screen.getAllByText("$12.00")).toHaveLength(2);
    expect(screen.getByText(/3 from Truck 1/)).toBeInTheDocument();
  });

  it("hides money from the field tier but still shows what was used", async () => {
    signedInAs("technician");
    renderPanel();

    expect(await screen.findByText("Sodium hypochlorite")).toBeInTheDocument();
    expect(screen.getByText(/3 from Truck 1/)).toBeInTheDocument();
    expect(screen.queryAllByText("$12.00")).toHaveLength(0);
  });

  it("returns stock instead of deleting the record", async () => {
    signedInAs("owner");
    const user = userEvent.setup();
    renderPanel();

    await screen.findByText("Sodium hypochlorite");
    await user.click(
      screen.getByRole("button", {
        name: "Return Sodium hypochlorite to stock",
      }),
    );

    await waitFor(() => {
      expect(removeJobMaterialMock).toHaveBeenCalledWith(
        "ws-1",
        "job-1",
        "entry-1",
      );
    });
  });

  it("offers no recording controls in read-only mode", async () => {
    signedInAs("owner");
    renderPanel(true);

    await screen.findByText("Sodium hypochlorite");
    expect(
      screen.queryByRole("button", { name: "Use on job" }),
    ).not.toBeInTheDocument();
  });
});
