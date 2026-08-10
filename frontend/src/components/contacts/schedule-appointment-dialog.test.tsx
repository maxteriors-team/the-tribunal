import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ScheduleAppointmentDialog } from "@/components/contacts/schedule-appointment-dialog";
import type { Contact } from "@/types";

const { mutateMock } = vi.hoisted(() => ({ mutateMock: vi.fn() }));

vi.mock("@/hooks/useAgents", () => ({
  useAgents: () => ({ data: { items: [] }, isPending: false }),
}));

vi.mock("@/hooks/useWorkspaceId", () => ({
  useWorkspaceId: () => "workspace-1",
}));

vi.mock("@/hooks/useCreateAppointment", () => ({
  useCreateAppointment: () => ({ mutate: mutateMock }),
}));

const contact = {
  id: 6978,
  user_id: 1,
  first_name: "Greg",
  last_name: "Bartlett",
  status: "converted",
  created_at: "2026-08-10T12:00:00Z",
  updated_at: "2026-08-10T12:00:00Z",
} as Contact;

beforeEach(() => {
  vi.clearAllMocks();
});

describe("ScheduleAppointmentDialog", () => {
  it("identifies the contact and blocks an incomplete booking", async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();

    render(
      <ScheduleAppointmentDialog
        contact={contact}
        open
        onOpenChange={onOpenChange}
      />,
    );

    expect(screen.getByRole("heading", { name: "Book appointment" })).toBeVisible();
    expect(screen.getByText(/Greg Bartlett/)).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Book appointment" }));

    expect(await screen.findByText("Please select a date")).toBeVisible();
    expect(mutateMock).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
