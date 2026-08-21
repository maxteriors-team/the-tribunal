import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { attendanceApi, type AttendanceEntry } from "@/lib/api/attendance";

import { TimeAttendancePage } from "./time-attendance-page";

const mockCan = vi.fn<(capability: string) => boolean>();

vi.mock("@/hooks/useWorkspaceId", () => ({ useWorkspaceId: () => "workspace-1" }));
vi.mock("@/hooks/useCapabilities", () => ({
  useCapabilities: () => ({ tier: "tech", can: mockCan }),
}));
vi.mock("@/providers/workspace-provider", () => ({
  useWorkspace: () => ({
    currentWorkspace: { workspace: { settings: { timezone: "UTC" } } },
  }),
}));
vi.mock("@/lib/api/attendance", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api/attendance")>();
  return {
    ...original,
    attendanceApi: {
      mine: vi.fn(),
      team: vi.fn(),
      clockIn: vi.fn(),
      clockOut: vi.fn(),
      pause: vi.fn(),
      resume: vi.fn(),
      updateEntry: vi.fn(),
      voidEntry: vi.fn(),
      exportCsv: vi.fn(),
    },
  };
});

const completeEntry: AttendanceEntry = {
  id: "entry-1",
  user_id: 10,
  employee_name: "Alex Operator",
  employee_email: "alex@example.com",
  started_at: "2026-08-20T13:00:00Z",
  ended_at: "2026-08-20T21:00:00Z",
  status: "complete",
  source: "clock",
  note: null,
  duration_seconds: 28_800,
  duration_hours: 8,
  gross_duration_seconds: 30_600,
  paused_seconds: 1_800,
  is_paused: false,
  pause_started_at: null,
  calculated_at: "2026-08-20T21:00:00Z",
  created_at: "2026-08-20T13:00:00Z",
  updated_at: "2026-08-20T21:00:00Z",
};

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <TimeAttendancePage />
    </QueryClientProvider>,
  );
}

describe("TimeAttendancePage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCan.mockImplementation((capability) => capability === "attendance:use");
    vi.mocked(attendanceApi.mine).mockResolvedValue({
      timezone: "America/New_York",
      entries: [completeEntry],
      total_seconds: 28_800,
      open_entry: null,
    });
    vi.mocked(attendanceApi.team).mockResolvedValue({
      timezone: "America/New_York",
      entries: [completeEntry],
      total_seconds: 28_800,
      open_count: 0,
      employee_count: 1,
    });
    vi.mocked(attendanceApi.updateEntry).mockResolvedValue({
      ...completeEntry,
      note: "Authenticated correction",
    });
    vi.mocked(attendanceApi.clockIn).mockResolvedValue({
      ...completeEntry,
      id: "entry-open",
      ended_at: null,
      status: "open",
      duration_seconds: 0,
      duration_hours: 0,
      gross_duration_seconds: 0,
      paused_seconds: 0,
      is_paused: false,
      pause_started_at: null,
      calculated_at: "2026-08-20T13:00:00Z",
    });
  });

  it("lets a staff member clock in and hides team hours", async () => {
    renderPage();

    expect(await screen.findByRole("button", { name: "Clock in" })).toBeVisible();
    expect(screen.queryByRole("tab", { name: "Team hours" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Clock in" }));

    await waitFor(() => {
      expect(attendanceApi.clockIn).toHaveBeenCalledWith(
        "workspace-1",
        expect.objectContaining({ request_id: expect.any(String) }),
      );
    });
  });

  it("lets a technician pause an active shift", async () => {
    const openEntry: AttendanceEntry = {
      ...completeEntry,
      id: "entry-open",
      ended_at: null,
      status: "open",
      duration_seconds: 3_600,
      duration_hours: 1,
      gross_duration_seconds: 3_600,
      paused_seconds: 0,
      is_paused: false,
      pause_started_at: null,
      calculated_at: new Date().toISOString(),
    };
    vi.mocked(attendanceApi.mine).mockResolvedValue({
      timezone: "America/New_York",
      entries: [openEntry],
      total_seconds: 3_600,
      open_entry: openEntry,
    });
    vi.mocked(attendanceApi.pause).mockResolvedValue({
      ...openEntry,
      is_paused: true,
      pause_started_at: new Date().toISOString(),
    });

    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Pause" }));

    await waitFor(() => {
      expect(attendanceApi.pause).toHaveBeenCalledWith(
        "workspace-1",
        expect.objectContaining({ request_id: expect.any(String) }),
      );
    });
  });

  it("shows a frozen worked timer and resume control while paused", async () => {
    const pausedEntry: AttendanceEntry = {
      ...completeEntry,
      id: "entry-paused",
      ended_at: null,
      status: "open",
      duration_seconds: 3_600,
      duration_hours: 1,
      gross_duration_seconds: 4_500,
      paused_seconds: 900,
      is_paused: true,
      pause_started_at: "2026-08-20T14:00:00Z",
      calculated_at: new Date().toISOString(),
    };
    vi.mocked(attendanceApi.mine).mockResolvedValue({
      timezone: "America/New_York",
      entries: [pausedEntry],
      total_seconds: 3_600,
      open_entry: pausedEntry,
    });
    vi.mocked(attendanceApi.resume).mockResolvedValue({
      ...pausedEntry,
      is_paused: false,
      pause_started_at: null,
    });

    renderPage();
    expect(await screen.findByText("Worked time is paused")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Resume" }));

    await waitFor(() => {
      expect(attendanceApi.resume).toHaveBeenCalledWith(
        "workspace-1",
        expect.objectContaining({ request_id: expect.any(String) }),
      );
    });
  });

  it("shows team review and payroll export only to attendance managers", async () => {
    mockCan.mockImplementation(
      (capability) => capability === "attendance:use" || capability === "attendance:manage",
    );
    vi.mocked(attendanceApi.exportCsv).mockResolvedValue({
      blob: new Blob(["employee_id,total_hours\r\n10,8.00\r\n"], { type: "text/csv" }),
      filename: "tribunal-hours.csv",
    });

    renderPage();

    const teamTab = await screen.findByRole("tab", { name: "Team hours" });
    await userEvent.click(teamTab);

    expect(
      await screen.findByText(/Generic payroll CSV separates gross, paused, and worked hours/i),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: /Export payroll CSV/i })).toBeEnabled();
    expect(attendanceApi.team).toHaveBeenCalled();
  });

  it("omits untouched timestamp fields from an audited note correction", async () => {
    mockCan.mockImplementation(
      (capability) => capability === "attendance:use" || capability === "attendance:manage",
    );
    renderPage();
    await userEvent.click(await screen.findByRole("tab", { name: "Team hours" }));
    await userEvent.click((await screen.findAllByRole("button", { name: "Edit" }))[0]);

    const dialog = screen.getByRole("dialog", { name: "Correct time entry" });
    await userEvent.type(within(dialog).getByLabelText("Entry note"), "Authenticated correction");
    await userEvent.type(within(dialog).getByLabelText("Correction reason"), "Verified source");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save correction" }));

    await waitFor(() => expect(attendanceApi.updateEntry).toHaveBeenCalled());
    const payload = vi.mocked(attendanceApi.updateEntry).mock.calls[0][2];
    expect(payload).toEqual(
      expect.objectContaining({
        note: "Authenticated correction",
        reason: "Verified source",
        request_id: expect.any(String),
      }),
    );
    expect(payload).not.toHaveProperty("started_at");
    expect(payload).not.toHaveProperty("ended_at");
  });

  it("fails closed when the active membership lacks attendance use", () => {
    mockCan.mockReturnValue(false);
    renderPage();

    expect(screen.getByText("Access denied")).toBeVisible();
    expect(attendanceApi.mine).not.toHaveBeenCalled();
  });
});
