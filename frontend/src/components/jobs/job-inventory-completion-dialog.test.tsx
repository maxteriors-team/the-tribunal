import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { JobInventoryCompletionDialog } from "@/components/jobs/job-inventory-completion-dialog";
import type { JobInventoryPlan } from "@/types/inventory";

const { completeMock, locationsMock } = vi.hoisted(() => ({
  completeMock: vi.fn(),
  locationsMock: vi.fn(),
}));

vi.mock("@/lib/api/jobs", () => ({
  jobsApi: { completeWithInventory: completeMock },
}));

vi.mock("@/lib/api/inventory", () => ({
  inventoryApi: { listLocations: locationsMock },
}));

const plan: JobInventoryPlan = {
  job_id: "job-1",
  job_status: "in_progress",
  completion_confirmation_required: true,
  allocations: [
    {
      id: "perm-ft",
      job_id: "job-1",
      item_id: "item-perm-ft",
      item_name: "Permanent Bistro footage",
      sku: "BISTRO-PERM-FT",
      unit_of_measure: "ft",
      behavior: "consumable",
      status: "reserved",
      planned_quantity: 180,
      actual_quantity: null,
      source_location_id: null,
      source_location_name: null,
      consumption_ledger_entry_id: null,
      quantity_on_hand: 200,
      quantity_reserved: 180,
      quantity_deployed: 0,
      available_to_promise: 20,
      shortage_quantity: 0,
      reserved_at: "2026-08-26T12:00:00Z",
      fulfilled_at: null,
      returned_at: null,
    },
    {
      id: "temp-set",
      job_id: "job-1",
      item_id: "item-temp-set",
      item_name: "Temporary Bistro set",
      sku: "BISTRO-TEMP-200FT",
      unit_of_measure: "set",
      behavior: "reusable",
      status: "reserved",
      planned_quantity: 2,
      actual_quantity: null,
      source_location_id: null,
      source_location_name: null,
      consumption_ledger_entry_id: null,
      quantity_on_hand: 3,
      quantity_reserved: 2,
      quantity_deployed: 0,
      available_to_promise: 1,
      shortage_quantity: 0,
      reserved_at: "2026-08-26T12:00:00Z",
      fulfilled_at: null,
      returned_at: null,
    },
  ],
};

function renderDialog() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onOpenChange = vi.fn();
  const onCompleted = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <JobInventoryCompletionDialog
        workspaceId="ws-1"
        jobId="job-1"
        plan={plan}
        open
        onOpenChange={onOpenChange}
        onCompleted={onCompleted}
      />
    </QueryClientProvider>,
  );
  return { onOpenChange, onCompleted };
}

describe("JobInventoryCompletionDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    locationsMock.mockResolvedValue([
      {
        id: "warehouse",
        name: "Warehouse",
        kind: "warehouse",
        is_active: true,
      },
    ]);
    completeMock.mockResolvedValue({ ...plan, job_status: "completed" });
  });

  it("prefills planned usage and labels permanent versus reusable behavior", () => {
    renderDialog();

    expect(screen.getByText("Consume and post COGS")).toBeInTheDocument();
    expect(screen.getByText("Deploy — reusable")).toBeInTheDocument();
    const actuals = screen.getAllByLabelText("Actual quantity");
    expect(actuals[0]).toHaveValue(180);
    expect(actuals[1]).toHaveValue(2);
  });

  it("shows a shortage before confirmation", async () => {
    const user = userEvent.setup();
    renderDialog();

    await user.clear(screen.getAllByLabelText("Actual quantity")[0]);
    await user.type(screen.getAllByLabelText("Actual quantity")[0], "201");

    expect(screen.getByText("Short by 1 ft for this actual quantity.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Post inventory and complete job" })).toBeDisabled();
  });

  it("submits every actual and completes atomically", async () => {
    const user = userEvent.setup();
    const { onCompleted } = renderDialog();

    await user.clear(screen.getAllByLabelText("Actual quantity")[0]);
    await user.type(screen.getAllByLabelText("Actual quantity")[0], "165");
    await user.click(screen.getByRole("button", { name: "Post inventory and complete job" }));

    await waitFor(() => {
      expect(completeMock).toHaveBeenCalledWith("ws-1", "job-1", {
        allocations: [
          { allocation_id: "perm-ft", actual_quantity: 165, source_location_id: null },
          { allocation_id: "temp-set", actual_quantity: 2, source_location_id: null },
        ],
      });
      expect(onCompleted).toHaveBeenCalled();
    });
  });
});
