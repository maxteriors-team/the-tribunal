import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { JobDetailDialog } from "@/components/jobs/job-detail-dialog";
import type { Job } from "@/lib/api/jobs";

/**
 * The read-only contract the dispatch board relies on.
 *
 * `JobsCalendar` passes `readOnly` whenever the caller lacks `jobs:write`, so
 * every dispatch mutation the backend rejects with 403 (schedule, status,
 * assign, delete) has to be absent from this dialog — not merely disabled.
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

const job: Job = {
  id: "job-1",
  workspace_id: "ws-1",
  contact_id: 1,
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
};

function renderDialog(readOnly: boolean) {
  return render(
    <JobDetailDialog
      workspaceId="ws-1"
      job={job}
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
