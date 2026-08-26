import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppointmentEditForm } from "@/components/calendar/appointment-edit-form";
import { appointmentsApi } from "@/lib/api/appointments";
import type { Appointment } from "@/types";

vi.mock("@/lib/api/appointments", () => ({
  appointmentsApi: { update: vi.fn() },
}));

const appointment: Appointment = {
  id: 42,
  contact_id: 7,
  workspace_id: "workspace-1",
  scheduled_at: "2026-09-10T14:00:00.000Z",
  anytime: false,
  duration_minutes: 30,
  status: "cancelled",
  service_type: "consultation",
  notes: "Original notes",
  created_at: "2026-08-01T00:00:00.000Z",
  updated_at: "2026-08-01T00:00:00.000Z",
};

describe("AppointmentEditForm", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(appointmentsApi.update).mockResolvedValue(appointment);
  });

  it("reschedules an appointment with edited calendar fields", async () => {
    const user = userEvent.setup();
    const onSaved = vi.fn();
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <AppointmentEditForm
          appointment={appointment}
          workspaceId="workspace-1"
          rescheduling
          onCancel={vi.fn()}
          onSaved={onSaved}
        />
      </QueryClientProvider>,
    );

    await user.clear(screen.getByLabelText("Date"));
    await user.type(screen.getByLabelText("Date"), "2026-09-20");
    await user.clear(screen.getByLabelText("Time"));
    await user.type(screen.getByLabelText("Time"), "11:45");
    await user.clear(screen.getByLabelText("Duration (minutes)"));
    await user.type(screen.getByLabelText("Duration (minutes)"), "60");
    await user.clear(screen.getByLabelText("Service"));
    await user.type(screen.getByLabelText("Service"), "Discovery call");
    await user.clear(screen.getByLabelText("Notes"));
    await user.type(screen.getByLabelText("Notes"), "Bring the estimate");
    await user.click(screen.getByRole("button", { name: "Save new time" }));

    await waitFor(() => {
      expect(appointmentsApi.update).toHaveBeenCalledWith("workspace-1", 42, {
        scheduled_at: new Date("2026-09-20T11:45:00").toISOString(),
        anytime: false,
        duration_minutes: 60,
        service_type: "Discovery call",
        notes: "Bring the estimate",
        status: "scheduled",
      });
    });
    expect(onSaved).toHaveBeenCalledOnce();
  });
});
