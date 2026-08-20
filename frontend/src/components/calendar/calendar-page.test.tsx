import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CalendarPage } from "@/components/calendar/calendar-page";
import type { AppointmentsListParams } from "@/lib/api/appointments";
import type { Job, JobList, JobListParams } from "@/lib/api/jobs";
import { can as roleCan, roleTier, type Capability } from "@/lib/permissions";
import type { Appointment } from "@/types";

/**
 * The unified calendar.
 *
 * Jobs and appointments used to live on two screens; they now share one grid.
 * These tests hold the merge honest — both species render together, each opens
 * its own detail dialog — and carry forward the dispatch-board behaviour that
 * moved here with the unscheduled queue.
 *
 * Role gating is checked from the *real* permission matrix (via a role string)
 * rather than a hand-written capability map, so these break if the matrix and
 * the UI gates ever drift apart.
 */

const {
  jobsListMock,
  jobsGetMock,
  appointmentsListMock,
  useWorkspaceIdMock,
  capabilitiesMock,
} = vi.hoisted(() => ({
  jobsListMock: vi.fn(),
  jobsGetMock: vi.fn(),
  appointmentsListMock: vi.fn(),
  useWorkspaceIdMock: vi.fn(),
  capabilitiesMock: vi.fn(),
}));

vi.mock("@/lib/api/jobs", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/jobs")>("@/lib/api/jobs");
  return {
    ...actual,
    jobsApi: { ...actual.jobsApi, list: jobsListMock, get: jobsGetMock },
  };
});

vi.mock("@/lib/api/appointments", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/api/appointments")>(
      "@/lib/api/appointments",
    );
  return {
    ...actual,
    appointmentsApi: { ...actual.appointmentsApi, list: appointmentsListMock },
  };
});

vi.mock("@/hooks/useWorkspaceId", () => ({
  useWorkspaceId: () => useWorkspaceIdMock(),
}));

vi.mock("@/hooks/useCapabilities", () => ({
  useCapabilities: () => capabilitiesMock(),
}));

// The location filter and the create dialogs run their own fetches and have
// their own tests. Stub them so this suite stays on the merge itself, and so a
// detail dialog is observable as a simple "did it open with this entry?".
vi.mock("@/components/locations/location-filter", () => ({
  LocationFilter: () => null,
}));
vi.mock("@/components/calendar/new-appointment-dialog", () => ({
  NewAppointmentDialog: () => null,
}));
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
vi.mock("@/components/calendar/appointment-details-dialog", () => ({
  AppointmentDetailsDialog: ({
    appointment,
    open,
  }: {
    appointment: Appointment | null;
    open: boolean;
  }) =>
    open && appointment ? (
      <div data-testid="appointment-detail-dialog">
        Detail: {appointment.service_type}
      </div>
    ) : null,
}));

function signedInAs(role: string) {
  capabilitiesMock.mockReturnValue({
    tier: roleTier(role),
    can: (capability: Capability) => roleCan(role, capability),
  });
}

// Both entry species are pinned to "now" so they land in the visible range
// whenever this suite runs, without freezing the clock.
const NOW = new Date();
function atHourToday(hour: number): string {
  const when = new Date(NOW);
  when.setHours(hour, 0, 0, 0);
  return when.toISOString();
}

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
    scheduled_start: atHourToday(10),
    scheduled_end: atHourToday(12),
    external_source: null,
    external_id: null,
    technicians: [],
    created_at: "2026-07-01T00:00:00.000Z",
    updated_at: "2026-07-01T00:00:00.000Z",
    ...overrides,
  };
}

function makeAppointment(overrides: Partial<Appointment> = {}): Appointment {
  return {
    id: 501,
    workspace_id: "ws-1",
    contact_id: 1,
    agent_id: null,
    scheduled_at: atHourToday(9),
    duration_minutes: 30,
    status: "scheduled",
    service_type: "Gutter estimate",
    notes: null,
    created_at: "2026-07-01T00:00:00.000Z",
    updated_at: "2026-07-01T00:00:00.000Z",
    ...overrides,
  } as Appointment;
}

const scheduledJob = makeJob();
const queuedJob = makeJob({
  id: "job-queued",
  title: "Garage EV charger install",
  status: "unscheduled",
  scheduled_start: null,
  scheduled_end: null,
});
const appointment = makeAppointment();

function jobList(items: Job[]): JobList {
  return { items, total: items.length };
}

function appointmentList(items: Appointment[]) {
  return { items, total: items.length, page: 1, page_size: 100, pages: 1 };
}

function renderCalendar(initialJobId?: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <CalendarPage initialJobId={initialJobId} />
    </QueryClientProvider>,
  );
}

/** Mirrors the backend: a windowed job query never returns null-start rows. */
function seedDefaultLists() {
  jobsListMock.mockImplementation((_ws: string, query: JobListParams = {}) =>
    Promise.resolve(
      query.status === "unscheduled" ? jobList([queuedJob]) : jobList([scheduledJob]),
    ),
  );
  appointmentsListMock.mockResolvedValue(appointmentList([appointment]));
}

beforeEach(() => {
  vi.clearAllMocks();
  useWorkspaceIdMock.mockReturnValue("ws-1");
  signedInAs("owner");
  jobsGetMock.mockResolvedValue(scheduledJob);
  seedDefaultLists();
});

describe("one calendar, both entry types", () => {
  it("renders jobs and appointments on the same grid", async () => {
    renderCalendar();

    expect(await screen.findAllByRole("button", { name: /^Job: Roof tune-up/ })).not.toHaveLength(
      0,
    );
    expect(
      screen.getAllByRole("button", { name: /^Appointment: Gutter estimate/ }),
    ).not.toHaveLength(0);
  });

  it("keeps mixed same-day entries and empty detail placeholders uniquely keyed", async () => {
    // The raw IDs intentionally collide while both unselected detail dialogs use
    // placeholder state. Type prefixes must keep all four React identities separate.
    const collidingJob = makeJob({ id: String(appointment.id) });
    jobsListMock.mockImplementation((_ws: string, query: JobListParams = {}) =>
      Promise.resolve(
        query.status === "unscheduled" ? jobList([queuedJob]) : jobList([collidingJob]),
      ),
    );
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);

    try {
      renderCalendar();

      expect(
        await screen.findAllByRole("button", { name: /^Appointment: Gutter estimate/ }),
      ).not.toHaveLength(0);
      expect(screen.getAllByRole("button", { name: /^Job: Roof tune-up/ })).not.toHaveLength(0);

      const duplicateKeyWarnings = consoleError.mock.calls.filter(([message]) =>
        String(message).includes("Encountered two children with the same key"),
      );
      expect(duplicateKeyWarnings).toEqual([]);
    } finally {
      consoleError.mockRestore();
    }
  });

  it("names each chip's species for assistive technology", async () => {
    // The wrench/clock icon and the accent rail are the visual signal; neither
    // reaches a screen reader, so the accessible name has to carry it.
    renderCalendar();

    const job = (await screen.findAllByRole("button", { name: /^Job: Roof tune-up/ }))[0];
    expect(job).toHaveAccessibleName(/^Job: Roof tune-up, \d{1,2}:\d{2} (AM|PM)$/);
  });

  it("counts each species separately", async () => {
    renderCalendar();
    expect(await screen.findByText(/1 appointment · 1 job/)).toBeInTheDocument();
  });

  it("opens the job dialog from a job chip", async () => {
    const user = userEvent.setup();
    renderCalendar();

    const chip = (await screen.findAllByRole("button", { name: /^Job: Roof tune-up/ }))[0];
    await user.click(chip);

    await waitFor(() =>
      expect(screen.getByTestId("job-detail-dialog")).toHaveTextContent(
        "Detail: Roof tune-up",
      ),
    );
    expect(screen.queryByTestId("appointment-detail-dialog")).not.toBeInTheDocument();
  });

  it("opens the appointment dialog from an appointment chip", async () => {
    const user = userEvent.setup();
    renderCalendar();

    const chip = (
      await screen.findAllByRole("button", { name: /^Appointment: Gutter estimate/ })
    )[0];
    await user.click(chip);

    await waitFor(() =>
      expect(screen.getByTestId("appointment-detail-dialog")).toHaveTextContent(
        "Detail: Gutter estimate",
      ),
    );
    expect(screen.queryByTestId("job-detail-dialog")).not.toBeInTheDocument();
  });

  it("renders both species in the week view too", async () => {
    const user = userEvent.setup();
    renderCalendar();

    await screen.findAllByRole("button", { name: /^Job: Roof tune-up/ });
    await user.click(screen.getByRole("button", { name: "week" }));

    expect(
      await screen.findAllByRole("button", { name: /^Job: Roof tune-up/ }),
    ).not.toHaveLength(0);
    expect(
      screen.getAllByRole("button", { name: /^Appointment: Gutter estimate/ }),
    ).not.toHaveLength(0);
  });

  it("applies shared status filters to both species", async () => {
    const user = userEvent.setup();
    appointmentsListMock.mockResolvedValue(
      appointmentList([
        appointment,
        makeAppointment({
          id: 502,
          status: "completed",
          service_type: "Finished estimate",
        }),
      ]),
    );
    jobsListMock.mockImplementation((_ws: string, query: JobListParams = {}) =>
      Promise.resolve(
        query.status === "unscheduled"
          ? jobList([queuedJob])
          : jobList([
              scheduledJob,
              makeJob({ id: "job-done", title: "Finished roof", status: "completed" }),
            ]),
      ),
    );
    renderCalendar();

    await screen.findAllByRole("button", { name: /^Job: Roof tune-up/ });
    await user.click(screen.getByRole("button", { name: "Completed" }));

    expect(screen.queryByRole("button", { name: /^Job: Roof tune-up/ })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^Appointment: Gutter estimate/ }),
    ).not.toBeInTheDocument();
    expect(await screen.findByText(/1 appointment · 1 job/)).toBeInTheDocument();
  });

  it("shows only jobs for the job-only In progress state", async () => {
    const user = userEvent.setup();
    jobsListMock.mockImplementation((_ws: string, query: JobListParams = {}) =>
      Promise.resolve(
        query.status === "unscheduled"
          ? jobList([queuedJob])
          : jobList([makeJob({ status: "in_progress" })]),
      ),
    );
    renderCalendar();

    await screen.findAllByRole("button", { name: /^Job: Roof tune-up/ });
    await user.click(screen.getByRole("button", { name: "In progress" }));

    expect(await screen.findByText(/0 appointments · 1 job/)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^Appointment: Gutter estimate/ }),
    ).not.toBeInTheDocument();
  });
});

/**
 * The dispatch queue moved here from the retired `/jobs` board.
 *
 * The range-scoped list drops null-start rows, so the queue keeps its own
 * `status=unscheduled` fetch with no date window — deriving it from the visible
 * range always came back empty.
 */
describe("unscheduled dispatch queue", () => {
  it("fetches the queue independently of the visible range", async () => {
    renderCalendar();

    expect(await screen.findAllByText("Garage EV charger install")).not.toHaveLength(0);
    expect(screen.queryByText("Nothing in the queue")).not.toBeInTheDocument();

    expect(jobsListMock).toHaveBeenCalledWith("ws-1", { status: "unscheduled" });
    expect(jobsListMock).toHaveBeenCalledWith(
      "ws-1",
      expect.objectContaining({
        date_from: expect.any(String),
        date_to: expect.any(String),
      }),
    );
  });

  it("opens the detail dialog for a job clicked from the queue", async () => {
    const user = userEvent.setup();
    renderCalendar();

    const panel = (await screen.findByText("Jobs waiting for a time window")).closest(
      '[data-slot="card"]',
    );
    await user.click(
      within(panel as HTMLElement).getByRole("button", {
        name: /Garage EV charger install/i,
      }),
    );

    // The queued job is not in the range-scoped list, so this only opens when
    // selection also resolves against the queue.
    await waitFor(() =>
      expect(screen.getByTestId("job-detail-dialog")).toHaveTextContent(
        "Detail: Garage EV charger install",
      ),
    );
  });

  it("does not inflate the range job count with queued jobs", async () => {
    renderCalendar();

    // The stat reads the range-scoped list (one dated job), never the queue —
    // which holds a second job that must not be counted here.
    const tile = (await screen.findByText("Jobs")).parentElement as HTMLElement;
    expect(within(tile).getByText("1")).toBeInTheDocument();
  });
});

/**
 * Capability gating.
 *
 * `jobs:write` is the dispatch line. Below it the API already returns a scoped
 * list, so the board affordances are not just hidden — they would be refused.
 */
describe("dispatch affordances are gated on jobs:write", () => {
  it("hides queue, New job, Only mine, and dead Settings from a field technician", async () => {
    signedInAs("technician");
    renderCalendar();

    await screen.findAllByRole("button", { name: /^Job: Roof tune-up/ });

    expect(screen.queryByText("Jobs waiting for a time window")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /New job/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Settings/i })).not.toBeInTheDocument();
    // Their view is already scoped server-side, so the filter would be a no-op.
    expect(screen.queryByLabelText("Only mine")).not.toBeInTheDocument();
    // The queue fetch must not even be attempted.
    expect(jobsListMock).not.toHaveBeenCalledWith("ws-1", { status: "unscheduled" });
  });

  it("keeps all three for a dispatcher", async () => {
    signedInAs("dispatcher");
    renderCalendar();

    await screen.findAllByRole("button", { name: /^Job: Roof tune-up/ });

    expect(screen.getByText("Jobs waiting for a time window")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /New job/i })).toBeInTheDocument();
    expect(screen.getByLabelText("Only mine")).toBeInTheDocument();
  });

  it("forces a read-only job dialog for a field technician", async () => {
    const user = userEvent.setup();
    signedInAs("technician");
    renderCalendar();

    const chip = (await screen.findAllByRole("button", { name: /^Job: Roof tune-up/ }))[0];
    await user.click(chip);

    await waitFor(() =>
      expect(screen.getByTestId("job-detail-dialog")).toHaveAttribute(
        "data-readonly",
        "true",
      ),
    );
  });

  it("scopes both lists to the caller when a dispatcher picks Only mine", async () => {
    const user = userEvent.setup();
    signedInAs("dispatcher");
    renderCalendar();

    await screen.findAllByRole("button", { name: /^Job: Roof tune-up/ });
    await user.click(screen.getByLabelText("Only mine"));

    // A merged calendar has to narrow both species or the filter lies.
    await waitFor(() =>
      expect(jobsListMock).toHaveBeenCalledWith(
        "ws-1",
        expect.objectContaining({ mine: true }),
      ),
    );
    await waitFor(() =>
      expect(appointmentsListMock).toHaveBeenCalledWith(
        "ws-1",
        expect.objectContaining({ mine: true } as Partial<AppointmentsListParams>),
      ),
    );
  });
});

describe("?job= deep link", () => {
  it("opens a job that falls outside the visible range", async () => {
    const linkedJob = makeJob({
      id: "job-linked",
      title: "Landscape lighting installation",
      scheduled_start: "2026-10-15T15:00:00.000Z",
      scheduled_end: "2026-10-15T17:00:00.000Z",
    });
    jobsGetMock.mockResolvedValue(linkedJob);

    renderCalendar("job-linked");

    expect(
      await screen.findByText("Detail: Landscape lighting installation"),
    ).toBeInTheDocument();
    expect(jobsGetMock).toHaveBeenCalledWith("ws-1", "job-linked");
  });
});
