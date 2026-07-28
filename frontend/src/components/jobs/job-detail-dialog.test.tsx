import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

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

const { mutation } = vi.hoisted(() => ({
  mutation: () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false }),
}));

vi.mock("@/hooks/useJobs", () => ({
  useWorkspaceTechnicians: () => ({ data: { items: [] } }),
  useScheduleJob: mutation,
  useUpdateJob: mutation,
  useAssignTechnicians: mutation,
  useUnassignTechnician: mutation,
  useDeleteJob: mutation,
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
  it("renders no dispatch write controls when read-only", () => {
    renderDialog(true);

    expect(screen.queryByRole("button", { name: /Save schedule/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Save assignments/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Delete job/i })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Status")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Start")).not.toBeInTheDocument();

    // The assignment roster is still readable, just not editable.
    expect(screen.getByText("Marco Reyes")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Details" })).toBeInTheDocument();
  });

  it("renders the full dispatch panel when writable", () => {
    renderDialog(false);

    expect(screen.getByRole("button", { name: /Save schedule/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Save assignments/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Delete job/i })).toBeInTheDocument();
    expect(screen.getByLabelText("Status")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Dispatch" })).toBeInTheDocument();
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
    renderDialog(true, makeJob({ customer: { id: 1349, name: "Helen Vasquez", phone_number: null } }));

    expect(screen.getByText("Helen Vasquez")).toBeInTheDocument();
    expect(screen.getByText("No phone number on file.")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Call/ })).not.toBeInTheDocument();
  });
});
