import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ServicePlanDialog } from "@/components/service-plans/service-plan-dialog";

const { createPlanMock } = vi.hoisted(() => ({ createPlanMock: vi.fn() }));

vi.mock("@/hooks/useWorkspaceId", () => ({
  useWorkspaceId: () => "workspace-1",
}));

vi.mock("@/hooks/useJobs", () => ({
  useWorkspaceTechnicians: () => ({
    data: {
      items: [
        {
          id: "tech-1",
          name: "Jordan Lee",
          color: "#2563eb",
          user_id: 22,
        },
      ],
    },
  }),
}));

vi.mock("@/components/ui/contact-combobox", () => ({
  FormContactPicker: ({
    value,
    onChange,
  }: {
    value: string;
    onChange: (value: string) => void;
  }) => (
    <select aria-label="Customer" value={value} onChange={(event) => onChange(event.target.value)}>
      <option value="">Choose customer</option>
      <option value="42">Lisa Homeowner</option>
    </select>
  ),
}));

vi.mock("@/lib/api/service-plans", () => ({
  servicePlansApi: {
    create: createPlanMock,
    update: vi.fn(),
  },
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

describe("ServicePlanDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    createPlanMock.mockResolvedValue({ id: "plan-1" });
  });

  it("passes tagged users to every generated job", async () => {
    const user = userEvent.setup();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <ServicePlanDialog open onOpenChange={vi.fn()} plan={null} />
      </QueryClientProvider>,
    );

    await user.selectOptions(screen.getByLabelText("Customer"), "42");
    await user.type(screen.getByLabelText("Title"), "Quarterly wash");
    fireEvent.change(screen.getByLabelText("First occurrence"), {
      target: { value: "2026-09-01T09:00" },
    });
    await user.click(screen.getByText("Jordan Lee"));
    fireEvent.submit(screen.getByRole("button", { name: "Create" }).closest("form")!);

    await waitFor(() => expect(createPlanMock).toHaveBeenCalled());
    expect(createPlanMock).toHaveBeenCalledWith(
      "workspace-1",
      expect.objectContaining({
        contact_id: 42,
        title: "Quarterly wash",
        default_technician_ids: ["tech-1"],
      }),
    );
  });
});
