import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { JobsPage } from "@/components/jobs/jobs-page";

const { canMock } = vi.hoisted(() => ({ canMock: vi.fn() }));

vi.mock("@/hooks/useCapabilities", () => ({
  useCapabilities: () => ({ can: canMock }),
}));

vi.mock("@/providers/workspace-provider", () => ({
  useWorkspace: () => ({ currentWorkspaceId: "workspace-1" }),
}));

vi.mock("@/hooks/useJobs", () => ({
  useJobs: () => ({
    data: {
      total: 1,
      items: [
        {
          id: "job-1",
          title: "Roofline install",
          status: "scheduled",
          scheduled_start: null,
          scheduled_end: null,
          customer: { name: "Ada Lovelace" },
          service_location: null,
          technicians: [],
        },
      ],
    },
    isPending: false,
    isError: false,
    refetch: vi.fn(),
  }),
}));

vi.mock("@/components/jobs/new-job-dialog", () => ({
  NewJobDialog: () => <div data-testid="new-job-dialog" />,
}));

vi.mock("@/components/jobs/job-detail-dialog", () => ({
  JobDetailDialog: ({ readOnly }: { readOnly?: boolean }) => (
    <div data-testid="job-detail-dialog" data-readonly={String(Boolean(readOnly))} />
  ),
}));

describe("JobsPage job mutation visibility", () => {
  beforeEach(() => vi.clearAllMocks());

  it("keeps creation and editing controls away from technicians", async () => {
    canMock.mockReturnValue(false);
    const user = userEvent.setup();
    render(<JobsPage />);

    expect(screen.queryByRole("button", { name: "New job" })).not.toBeInTheDocument();
    expect(screen.queryByTestId("new-job-dialog")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Roofline install" }));
    expect(screen.getByTestId("job-detail-dialog")).toHaveAttribute("data-readonly", "true");
  });

  it("keeps creation and editing controls available to dispatchers", async () => {
    canMock.mockReturnValue(true);
    const user = userEvent.setup();
    render(<JobsPage />);

    expect(screen.getByRole("button", { name: "New job" })).toBeInTheDocument();
    expect(screen.getByTestId("new-job-dialog")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Roofline install" }));
    expect(screen.getByTestId("job-detail-dialog")).toHaveAttribute("data-readonly", "false");
  });
});
