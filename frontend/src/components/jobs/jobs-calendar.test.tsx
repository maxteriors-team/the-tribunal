import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { JobsCalendar } from "@/components/jobs/jobs-calendar";
import type { Job, JobList, JobListParams } from "@/lib/api/jobs";
import { can as roleCan, roleTier, type Capability } from "@/lib/permissions";

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

const { listMock, listMineMock, useWorkspaceIdMock, capabilitiesMock } = vi.hoisted(() => ({
  listMock: vi.fn(),
  listMineMock: vi.fn(),
  useWorkspaceIdMock: vi.fn(),
  capabilitiesMock: vi.fn(),
}));

vi.mock("@/lib/api/jobs", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/jobs")>("@/lib/api/jobs");
  return {
    ...actual,
    jobsApi: { ...actual.jobsApi, list: listMock, listMine: listMineMock },
  };
});

vi.mock("@/hooks/useWorkspaceId", () => ({
  useWorkspaceId: () => useWorkspaceIdMock(),
}));

// Capabilities come from the workspace membership role, which needs a provider.
// Drive them from a role string through the *real* permission matrix so these
// tests break if the matrix and the UI gates drift apart.
vi.mock("@/hooks/useCapabilities", () => ({
  useCapabilities: () => capabilitiesMock(),
}));

function signedInAs(role: string) {
  capabilitiesMock.mockReturnValue({
    tier: roleTier(role),
    can: (capability: Capability) => roleCan(role, capability),
  });
}

// The child dialogs run their own fetches (technicians, costing) and have their
// own tests. Stub them so this suite stays focused on the board's queue wiring,
// and so the detail dialog is observable as a simple "did it open with this job?".
vi.mock("@/components/jobs/new-job-dialog", () => ({
  NewJobDialog: () => null,
}));
vi.mock("@/components/jobs/job-detail-dialog", () => ({
  JobDetailDialog: ({
    job,
    open,
    readOnly,
  }: {
    job: Job | null;
    open: boolean;
    readOnly?: boolean;
  }) =>
    open && job ? (
      <div data-testid="job-detail-dialog" data-readonly={String(Boolean(readOnly))}>
        Detail: {job.title}
      </div>
    ) : null,
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
    signedInAs("owner");
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

/**
 * Role scoping for the dispatch board.
 *
 * The backend gates create/update/delete/schedule/assign on `WorkspaceDispatcher`,
 * so a field technician (jobs:read only) got a fully editable dispatch panel that
 * 403'd on every click. Read-only used to be wired to the "My jobs" toggle — a
 * view preference — instead of the caller's capability.
 */
describe("JobsCalendar role scoping", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useWorkspaceIdMock.mockReturnValue("ws-1");
    listMock.mockImplementation((_ws: string, query: JobListParams = {}) =>
      Promise.resolve(
        query.status === "unscheduled" ? jobList([queuedJob]) : jobList([scheduledJob]),
      ),
    );
  });

  // The seeded week job falls outside the current week, so open the job from
  // the always-rendered "Unscheduled" queue instead.
  async function openQueuedJob() {
    const user = userEvent.setup();
    const cards = await screen.findAllByRole("button", { name: /Garage EV charger install/i });
    await user.click(cards[0]);
    return waitFor(() => screen.getByTestId("job-detail-dialog"));
  }

  it("hides create and forces a read-only detail view for a field technician", async () => {
    signedInAs("technician");
    renderBoard();

    await screen.findAllByText("Garage EV charger install");
    // Creating a job is dispatcher-only, and its customer picker is 403 for a
    // technician — the button must not be offered at all.
    expect(screen.queryByRole("button", { name: /New Job/i })).not.toBeInTheDocument();

    // Board view, "My jobs" off — read-only still has to come from the role.
    expect(await openQueuedJob()).toHaveAttribute("data-readonly", "true");
  });

  it("keeps the full dispatch experience for a write-capable role", async () => {
    signedInAs("owner");
    renderBoard();

    await screen.findAllByText("Garage EV charger install");
    expect(screen.getByRole("button", { name: /New Job/i })).toBeInTheDocument();
    expect(await openQueuedJob()).toHaveAttribute("data-readonly", "false");
  });

  it("still drops a dispatcher into read-only on their own calendar", async () => {
    const user = userEvent.setup();
    listMineMock.mockResolvedValue(jobList([queuedJob]));
    signedInAs("dispatcher");
    renderBoard();

    await screen.findAllByText("Garage EV charger install");
    await user.click(screen.getByLabelText("My jobs"));

    expect(await openQueuedJob()).toHaveAttribute("data-readonly", "true");
  });
});

/**
 * The agenda a worker actually reads on a phone.
 *
 * A job card that only shows a title and a time doesn't say where to drive, so
 * the single-column agenda (and the unscheduled queue that shares its card)
 * also carries the customer and the street line from the job's embedded site.
 * The seven-across week grid stays lean — a column there is too narrow.
 */
describe("JobsCalendar job cards", () => {
  const sitedJob = makeJob({
    id: "job-sited",
    title: "Soft wash — two-story siding",
    status: "unscheduled",
    scheduled_start: null,
    scheduled_end: null,
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
      access_notes: null,
      latitude: null,
      longitude: null,
    },
  });

  beforeEach(() => {
    vi.clearAllMocks();
    useWorkspaceIdMock.mockReturnValue("ws-1");
    signedInAs("technician");
  });

  it("puts the customer and street line on the agenda card", async () => {
    listMock.mockImplementation((_ws: string, query: JobListParams = {}) =>
      Promise.resolve(query.status === "unscheduled" ? jobList([sitedJob]) : jobList([])),
    );
    renderBoard();

    const card = (await screen.findAllByRole("button", { name: /Soft wash/i }))[0];
    expect(within(card).getByText("Helen Vasquez")).toBeInTheDocument();
    expect(within(card).getByText("4412 Ridgeview Dr")).toBeInTheDocument();
    expect(card.textContent).not.toMatch(/[$€£]/);
  });

  it("renders a card with no customer or site without crashing", async () => {
    listMock.mockImplementation((_ws: string, query: JobListParams = {}) =>
      Promise.resolve(query.status === "unscheduled" ? jobList([queuedJob]) : jobList([])),
    );
    renderBoard();

    const card = (await screen.findAllByRole("button", { name: /Garage EV charger install/i }))[0];
    expect(within(card).getByText("Garage EV charger install")).toBeInTheDocument();
    expect(within(card).getByText("Unassigned")).toBeInTheDocument();
  });
});
