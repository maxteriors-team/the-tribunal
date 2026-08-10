import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { QuickActionsSection } from "@/components/actions/quick-actions-section";

const { scheduleDialogPropsMock } = vi.hoisted(() => ({
  scheduleDialogPropsMock: vi.fn(),
}));

const selectedContact = {
  id: 6978,
  first_name: "Greg",
  last_name: "Bartlett",
  phone_number: "+13136904003",
};

vi.mock("@/lib/contact-store", () => ({
  useContactStore: () => ({ selectedContact }),
}));

vi.mock("@/components/invoices/invoice-create-dialog", () => ({
  InvoiceCreateDialog: () => null,
}));

vi.mock("@/components/contacts/schedule-appointment-dialog", () => ({
  ScheduleAppointmentDialog: (props: { contact: typeof selectedContact; open: boolean }) => {
    scheduleDialogPropsMock(props);
    return props.open ? <div role="dialog">Appointment scheduler</div> : null;
  },
}));


beforeEach(() => {
  vi.clearAllMocks();
});

describe("QuickActionsSection", () => {
  it("opens the real appointment scheduler for the selected contact", async () => {
    const user = userEvent.setup();
    render(<QuickActionsSection />);

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getAllByRole("button").map((button) => button.textContent)).toEqual([
      "Send Invoice",
      "Schedule",
    ]);

    await user.click(screen.getByRole("button", { name: "Schedule" }));

    expect(screen.getByRole("dialog")).toHaveTextContent("Appointment scheduler");
    expect(scheduleDialogPropsMock).toHaveBeenLastCalledWith(
      expect.objectContaining({
        contact: selectedContact,
        open: true,
      }),
    );
  });
});
