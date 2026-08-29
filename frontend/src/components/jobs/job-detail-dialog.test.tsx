import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { JobDetailDialog } from "@/components/jobs/job-detail-dialog";
import type { Job } from "@/lib/api/jobs";

/**
 * The read-only contract the dispatch board relies on, plus the field brief.
 *
 * `JobsCalendar` passes `readOnly` whenever the caller lacks `jobs:write`, so
 * every dispatch mutation the backend rejects with 403 (schedule, status,
 * assign, delete) has to be absent from this dialog — not merely disabled.
 *
 * The brief (site, customer, access notes, scope) is the other half: a
 * technician holds `jobs:read` only and cannot fetch the contact or the service
 * location, so if this dialog doesn't render the embedded projections they have
 * no way to find the job. It renders for both roles, and never shows money.
 */

const { mutation, installationPlanQuery, inventoryPlanMock, handoffImagesMock, canvasContext } = vi.hoisted(() => ({
  mutation: () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false }),
  installationPlanQuery: vi.fn(),
  inventoryPlanMock: vi.fn(),
  handoffImagesMock: vi.fn(),
  canvasContext: {
    clearRect: vi.fn(),
    drawImage: vi.fn(),
    fillRect: vi.fn(),
    strokeRect: vi.fn(),
    beginPath: vi.fn(),
    closePath: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    arc: vi.fn(),
    fill: vi.fn(),
    stroke: vi.fn(),
    save: vi.fn(),
    restore: vi.fn(),
    translate: vi.fn(),
    rotate: vi.fn(),
    scale: vi.fn(),
    setTransform: vi.fn(),
    fillText: vi.fn(),
    measureText: vi.fn(() => ({ width: 10 })),
    createLinearGradient: vi.fn(() => ({ addColorStop: vi.fn() })),
  },
}));

vi.mock("@/lib/api/jobs", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/jobs")>();
  return { ...actual, jobsApi: { ...actual.jobsApi, inventoryPlan: inventoryPlanMock } };
});

vi.mock("@/components/jobs/handoff-images", () => ({
  HandoffImages: (props: Record<string, string>) => {
    handoffImagesMock(props);
    return <section aria-label="Field handoff images" />;
  },
}));

vi.mock("@/components/jobs/job-inventory-completion-dialog", () => ({
  JobInventoryCompletionDialog: () => <div>Confirm Bistro inventory</div>,
}));

vi.mock("@/hooks/useJobs", () => ({
  useWorkspaceTechnicians: () => ({ data: { items: [] } }),
  useJobInstallationPlan: () => installationPlanQuery(),
  useScheduleJob: mutation,
  useUpdateJob: mutation,
  useAssignTechnicians: mutation,
  useUnassignTechnician: mutation,
  useDeleteJob: mutation,
}));

vi.mock("@/lib/estimator/photo", () => ({
  loadImage: vi.fn().mockResolvedValue({ naturalWidth: 1200, naturalHeight: 800 }),
}));

// Field-work costing has its own suite; keep this one on the dispatch tab.
vi.mock("@/components/jobs/job-costing-panel", () => ({
  JobCostingPanel: () => null,
}));

function makeJob(overrides: Partial<Job> = {}): Job {
  return {
    id: "job-1",
    workspace_id: "ws-1",
    contact_id: 1349,
    service_location_id: null,
    crew_id: null,
    title: "Roof tune-up",
    description: null,
    status: "scheduled",
    scheduled_start: "2026-07-15T15:00:00.000Z",
    scheduled_end: "2026-07-15T17:00:00.000Z",
    external_source: null,
    external_id: null,
    technicians: [{ id: "tech-1", name: "Marco Reyes", color: "#2563eb" }],
    created_at: "2026-07-01T00:00:00.000Z",
    updated_at: "2026-07-01T00:00:00.000Z",
    ...overrides,
  };
}

/** A fully populated job, matching the shape the API returns to the field. */
const fullJob = makeJob({
  description: "Customer requested a call 30 min before arrival.",
  customer: { id: 1349, name: "Helen Vasquez", phone_number: "+15125550142" },
  service_location: {
    id: "site-1",
    name: "Helen Vasquez residence",
    address_line1: "4412 Ridgeview Dr",
    address_line2: null,
    city: "Austin",
    state: "TX",
    postal_code: "78731",
    country: "US",
    access_notes: "Gate code 4417. Dog in back yard — leash before starting.",
    latitude: null,
    longitude: null,
  },
  line_items: [
    {
      id: "li-1",
      name: "Soft wash - two-story siding",
      description: "House wash, low-pressure detergent, all four elevations",
      quantity: 1,
    },
    {
      id: "li-2",
      name: "Gutter face brightening",
      description: null,
      quantity: 2,
    },
  ],
});

function renderDialog(readOnly: boolean, jobToRender: Job = fullJob) {
  return render(
    <JobDetailDialog
      workspaceId="ws-1"
      job={jobToRender}
      open
      onOpenChange={vi.fn()}
      readOnly={readOnly}
    />,
  );
}

describe("JobDetailDialog", () => {
  beforeEach(() => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(
      canvasContext as unknown as CanvasRenderingContext2D,
    );
    installationPlanQuery.mockReturnValue({
      isPending: false,
      isError: false,
      data: undefined,
      refetch: vi.fn(),
    });
    inventoryPlanMock.mockResolvedValue({
      job_id: "job-1",
      job_status: "scheduled",
      completion_confirmation_required: true,
      allocations: [{ id: "allocation-1" }],
    });
  });
  it("renders no dispatch write controls when read-only", () => {
    renderDialog(true);

    expect(screen.queryByRole("button", { name: /Save schedule/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Save assignments/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Delete job/i })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Status")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Start")).not.toBeInTheDocument();

    // The assignment roster and time tracking remain available to the field member.
    expect(screen.getByText("Marco Reyes")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Details" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Time tracking" })).toBeInTheDocument();
  });

  it("renders the full dispatch panel when writable", () => {
    renderDialog(false);

    expect(screen.getByRole("button", { name: /Save schedule/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Save assignments/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Delete job/i })).toBeInTheDocument();
    expect(screen.getByLabelText("Status")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Dispatch" })).toBeInTheDocument();
  });

  it.each([true, false])("renders job handoff images (readOnly=%s)", (readOnly) => {
    renderDialog(readOnly);

    expect(screen.getByRole("region", { name: "Field handoff images" })).toBeInTheDocument();
    expect(handoffImagesMock).toHaveBeenLastCalledWith({
      mode: "job",
      workspaceId: "ws-1",
      jobId: "job-1",
    });
  });

  it("opens inventory confirmation instead of patching completed directly", async () => {
    const user = userEvent.setup();
    renderDialog(false);

    await user.click(screen.getByLabelText("Status"));
    await user.click(screen.getByRole("option", { name: "Completed" }));

    expect(inventoryPlanMock).toHaveBeenCalledWith("ws-1", "job-1");
    expect(await screen.findByText("Confirm Bistro inventory")).toBeInTheDocument();
  });

  it("loads only the selected read-only installation plan and exposes print/download", async () => {
    installationPlanQuery.mockReturnValue({
      isPending: false,
      isError: false,
      refetch: vi.fn(),
      data: {
        job_id: "job-1",
        project_id: "project-1",
        project_name: "Front elevation",
        project_version: 4,
        project_updated_at: "2026-08-12T00:00:00Z",
        selected_shot_id: "install-front",
        proposal_preview_image: "data:image/jpeg;base64,/9j/2Q==",
        proposal_preview_caption: "Approved permanent lighting preview",
        proposal_status: "approved",
        proposal_accepted_at: "2026-08-12T01:00:00Z",
        payment_status: "paid",
        payment_received_at: "2026-08-12T01:05:00Z",
        sheet_label: "Front",
        drawing_title: "Installation plan",
        drawing_number: "L-1",
        photo: { dataUrl: "data:image/png;base64,AAAA", width: 1200, height: 800 },
        design: { calibration: null, runs: [], items: [], planImages: [] },
        dusk: 0.35,
        settings: {},
        fixture_schedule: [{ number: 1, item_id: "fixture-1", catalog_sku: "UP-01" }],
        precon_field_brief: "Confirm transformer location.",
      },
    });
    renderDialog(true, { ...fullJob, lighting_project_id: "project-1" });
    await userEvent.click(screen.getByRole("tab", { name: "Installation plan" }));

    expect(await screen.findByRole("heading", { name: "Installation plan" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Customer proposal" })).toBeVisible();
    expect(screen.getByText("Proposal accepted")).toBeVisible();
    expect(screen.getByText("Customer payment received")).toBeVisible();
    expect(
      screen.getByRole("img", { name: "Approved permanent lighting preview" }),
    ).toHaveAttribute("src", "data:image/jpeg;base64,/9j/2Q==");
    expect(screen.getByText(/Confirm transformer location/)).toBeInTheDocument();
    expect(screen.getByText(/UP-01/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Print/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Download PNG/ })).toBeInTheDocument();
    expect(screen.queryByText(/deposit|procurement/i)).not.toBeInTheDocument();
  });
});

describe("JobDetailDialog field brief", () => {
  it.each([true, false])("shows the site, customer and scope (readOnly=%s)", (readOnly) => {
    renderDialog(readOnly);

    // Customer name replaces the raw `Customer #1349` database id.
    expect(screen.getByText(/Helen Vasquez ·/)).toBeInTheDocument();
    expect(screen.queryByText(/Customer #/)).not.toBeInTheDocument();

    // Tap-to-call.
    const call = screen.getByRole("link", { name: /Call \+1 \(512\) 555-0142/ });
    expect(call).toHaveAttribute("href", "tel:+15125550142");

    // Address block + tap-to-navigate (URL-encoded, no map pin on this job).
    expect(screen.getByText("4412 Ridgeview Dr")).toBeInTheDocument();
    expect(screen.getByText("Austin, TX 78731")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Navigate/ })).toHaveAttribute(
      "href",
      "https://maps.google.com/?q=4412%20Ridgeview%20Dr%2C%20Austin%2C%20TX%2078731",
    );

    // Access notes: safety/entry info, called out separately.
    expect(screen.getByRole("heading", { name: /Access notes/ })).toBeInTheDocument();
    expect(screen.getByText(/Gate code 4417/)).toBeInTheDocument();

    // Scope of work, with quantities and no prices anywhere.
    const scope = screen.getByRole("heading", { name: /Scope of work/ }).parentElement!;
    expect(within(scope).getByText("Soft wash - two-story siding")).toBeInTheDocument();
    expect(
      within(scope).getByText("House wash, low-pressure detergent, all four elevations"),
    ).toBeInTheDocument();
    expect(within(scope).getByText(/×\s*2/)).toBeInTheDocument();
    expect(scope.textContent).not.toMatch(/[$€£]/);
  });

  it("prefers the map pin over the typed address when the site has one", () => {
    renderDialog(true, {
      ...fullJob,
      service_location: { ...fullJob.service_location!, latitude: 30.35, longitude: -97.77 },
    });

    expect(screen.getByRole("link", { name: /Navigate/ })).toHaveAttribute(
      "href",
      "https://maps.google.com/?q=30.35,-97.77",
    );
  });

  it("renders empty states instead of blank gaps when the extras are missing", () => {
    // The API marks all three as optional; older jobs come back without them.
    renderDialog(true, makeJob({ customer: null, service_location: null, line_items: [] }));

    expect(screen.getByText("No site address on this job.")).toBeInTheDocument();
    expect(screen.getByText("No customer contact on this job.")).toBeInTheDocument();
    expect(screen.getByText("No scope items on this job yet.")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Navigate/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Call/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /Access notes/ })).not.toBeInTheDocument();

    // The header still says something useful without a customer name.
    expect(screen.getByText(/Wed, Jul 15 at/)).toBeInTheDocument();
  });

  it("keeps the call action off a customer with no phone number", () => {
    renderDialog(
      true,
      makeJob({ customer: { id: 1349, name: "Helen Vasquez", phone_number: null } }),
    );

    expect(screen.getByText("Helen Vasquez")).toBeInTheDocument();
    expect(screen.getByText("No phone number on file.")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Call/ })).not.toBeInTheDocument();
  });
});
