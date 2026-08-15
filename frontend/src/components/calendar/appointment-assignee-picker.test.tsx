import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AppointmentAssigneePicker } from "@/components/calendar/appointment-assignee-picker";

vi.mock("@/hooks/useJobs", () => ({
  useWorkspaceBookableStaff: () => ({
    data: {
      items: [
        {
          id: "staff-jordan",
          workspace_id: "workspace-1",
          agent_id: null,
          name: "Jordan Lee",
          email: "jordan@example.com",
          user_id: 22,
          skills: [],
          is_active: true,
          priority: 10,
          assignment_count: 0,
          last_assigned_at: null,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        },
      ],
      total: 1,
    },
    isPending: false,
    isError: false,
  }),
}));

describe("AppointmentAssigneePicker", () => {
  it("tags a booking-enabled workspace user", async () => {
    const user = userEvent.setup();
    const onValueChange = vi.fn();
    render(
      <AppointmentAssigneePicker
        workspaceId="workspace-1"
        value={null}
        onValueChange={onValueChange}
      />,
    );

    await user.click(screen.getByRole("combobox", { name: "Assigned user" }));
    await user.click(screen.getByRole("option", { name: /Jordan Lee/ }));

    expect(onValueChange).toHaveBeenCalledWith("staff-jordan");
  });

  it("can remove the current user tag", async () => {
    const user = userEvent.setup();
    const onValueChange = vi.fn();
    render(
      <AppointmentAssigneePicker
        workspaceId="workspace-1"
        value="staff-jordan"
        onValueChange={onValueChange}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Unassign Jordan Lee" }));

    expect(onValueChange).toHaveBeenCalledWith(null);
  });
});
