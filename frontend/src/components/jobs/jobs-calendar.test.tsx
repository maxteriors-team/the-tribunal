import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { JobsCalendar } from "@/components/jobs/jobs-calendar";
import type { Job, JobList, JobListParams } from "@/lib/api/jobs";

/**
 * Regression cover for the dispatch board's "Unscheduled" queue.
 *
 * The board list is scoped to the visible week (`date_from`/`date_to`), and the
 * backend drops null-start rows from any windowed query — so deriving the queue
 * from that list always came back empty ("Nothing in the queue") even when
 * unscheduled jobs existed. The fix fetches the queue with its own
 * `status=unscheduled` query (no date range) and resolves the clicked job from
 * that list too, while leaving the week list — and its "This week" count — alone.
 */

const { listMock, useWorkspaceIdMock } = vi.hoisted(() => ({
  listMock: vi.fn(),
  useWorkspaceIdMock: vi.fn(),
}));

vi.mock("@/lib/api/jobs", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/jobs")>("@/lib/api/jobs");
  return {
    ...actual,
    jobsApi: { ...actual.jobsApi, list: listMock },
  };
});

vi.mock("@/hooks/useWorkspaceId", () => ({
  useWorkspaceId: () => useWorkspaceIdMock(),
}));

// The child dialogs run their own fetches (technicians, costing) and have their
// own tests. Stub them so this suite stays focused on the board's queue wiring,
// and so the detail dialog is observable as a simple "did it open with this job?".
vi.mock("@/components/jobs/new-job-dialog", () => ({
  NewJobDialog: () => null,
}));
vi.mock("@/components/jobs/job-detail-dialog", () => ({
  JobDetailDialog: ({ job, open }: { job: Job | null; open: boolean }) =>
    open && job ? <div data-testid="job-detail-dialog">Detail: {job.title}</div> : null,
}));

function makeJob(overrides: Partial<Job> = {}): Job {
  return {
    id: "job-scheduled",
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
    technicians: [],
    created_at: "2026-07-01T00:00:00.000Z",
    updated_at: "2026-07-01T00:00:00.000Z",
    ...overrides,
  };
}

const scheduledJob = makeJob();
const queuedJob = makeJob({
  id: "job-queued",
  title: "Garage EV charger install",
  status: "unscheduled",
  scheduled_start: null,
  scheduled_end: null,
});

function jobList(items: Job[]): JobList {
  return { items, total: items.length };
}

function renderBoard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <JobsCalendar />
    </QueryClientProvider>,
  );
}

describe("JobsCalendar unscheduled queue", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useWorkspaceIdMock.mockReturnValue("ws-1");
    // Mirror the backend: the week-scoped list (has date_from/date_to) never
    // returns null-start jobs; the queue is a separate status=unscheduled fetch.
    listMock.mockImplementation((_ws: string, query: JobListParams = {}) =>
      Promise.resolve(
        query.status === "unscheduled" ? jobList([queuedJob]) : jobList([scheduledJob]),
      ),
    );
  });

  it("lists unscheduled jobs from a week-independent query", async () => {
    renderBoard();

    // The panel is populated from the dedicated query, not "Nothing in the queue".
    expect(await screen.findAllByText("Garage EV charger install")).not.toHaveLength(0);
    expect(screen.queryByText("Nothing in the queue")).not.toBeInTheDocument();

    // The queue fetch carries no date range, so switching weeks can't drop it,
    // and it is fetched separately from the week-scoped board list.
    expect(listMock).toHaveBeenCalledWith("ws-1", { status: "unscheduled" });
    expect(listMock).toHaveBeenCalledWith(
      "ws-1",
      expect.objectContaining({
        date_from: expect.any(String),
        date_to: expect.any(String),
      }),
    );
  });

  it("does not inflate the This week count with unscheduled jobs", async () => {
    renderBoard();

    // The count comes from the week-scoped list (one dated job), never the queue.
    const label = await screen.findByText("Total jobs");
    const content = label.closest('[data-slot="card-content"]');
    expect(content).not.toBeNull();
    expect(within(content as HTMLElement).getByText("1")).toBeInTheDocument();
  });

  it("opens the detail dialog for a job clicked from the queue", async () => {
    const user = userEvent.setup();
    renderBoard();

    await screen.findAllByText("Garage EV charger install");
    expect(screen.queryByTestId("job-detail-dialog")).not.toBeInTheDocument();

    // Click the queued job from the desktop "Unscheduled" panel.
    const panel = screen
      .getByText("Jobs waiting for a time window")
      .closest('[data-slot="card"]');
    const button = within(panel as HTMLElement).getByRole("button", {
      name: /Garage EV charger install/i,
    });
    await user.click(button);

    // The clicked job isn't in the week-scoped list, so this only opens when
    // selection also resolves against the queue.
    await waitFor(() =>
      expect(screen.getByTestId("job-detail-dialog")).toHaveTextContent(
        "Detail: Garage EV charger install",
      ),
    );
  });
});
