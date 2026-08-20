import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OpportunityCardSummary } from "@/components/opportunities/opportunity-card";
import { OpportunityCreateSheet } from "@/components/opportunities/opportunity-create-sheet";
import { OpportunityDetailSheet } from "@/components/opportunities/opportunity-detail-sheet";
import type { Opportunity, PipelineStage } from "@/types";

const { createMock, getMock, updateMock, moveMock, toastMock } = vi.hoisted(() => ({
  createMock: vi.fn(),
  getMock: vi.fn(),
  updateMock: vi.fn(),
  moveMock: vi.fn(),
  toastMock: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/lib/api/opportunities", () => ({
  opportunitiesApi: {
    create: createMock,
    get: getMock,
    update: updateMock,
    move: moveMock,
  },
}));

vi.mock("@/components/workspaces/team-member-picker", () => ({
  TeamMemberPicker: ({
    value,
    onValueChange,
    label,
  }: {
    value: number | null;
    onValueChange: (value: number | null) => void;
    label?: string;
  }) => (
    <label>
      {label}
      <select
        aria-label={label}
        value={value ?? ""}
        onChange={(event) => onValueChange(event.target.value ? Number(event.target.value) : null)}
      >
        <option value="">Unassigned</option>
        <option value="7">Morgan Manager</option>
      </select>
    </label>
  ),
}));

vi.mock("sonner", () => ({ toast: toastMock }));

const stages: PipelineStage[] = [
  {
    id: "stage-1",
    pipeline_id: "pipeline-1",
    name: "Qualified",
    order: 0,
    probability: 40,
    stage_type: "active",
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
  },
];

const opportunity: Opportunity = {
  id: "opportunity-1",
  workspace_id: "ws-1",
  pipeline_id: "pipeline-1",
  stage_id: "stage-1",
  name: "Roof replacement",
  status: "open",
  probability: 40,
  currency: "USD",
  assigned_user_id: 4,
  assignee: { id: 4, full_name: "Avery Owner", email: "avery@example.com" },
  is_active: true,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

let queryClient: QueryClient;

function QueryWrapper({ children }: { children: React.ReactNode }) {
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

describe("opportunity ownership", () => {
  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    vi.clearAllMocks();
    createMock.mockResolvedValue(opportunity);
    getMock.mockResolvedValue(opportunity);
    updateMock.mockResolvedValue({
      ...opportunity,
      assigned_user_id: 7,
      assignee: { id: 7, full_name: "Morgan Manager", email: "morgan@example.com" },
    });
  });

  it("lets a manager select an owner while creating", async () => {
    render(
      <OpportunityCreateSheet
        workspaceId="ws-1"
        pipelineId="pipeline-1"
        stages={stages}
        defaultStageId="stage-1"
        contactId={42}
        contact={{ id: 42, first_name: "Helen", last_name: "Vasquez" }}
        canAssignOwners
        open
        onOpenChange={vi.fn()}
      />,
      { wrapper: QueryWrapper },
    );

    await userEvent.type(screen.getByLabelText("Name *"), "New deal");
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Owner" }), "7");
    await userEvent.click(screen.getByRole("button", { name: "Create Opportunity" }));

    await waitFor(() =>
      expect(createMock).toHaveBeenCalledWith(
        "ws-1",
        expect.objectContaining({ assigned_user_id: 7 }),
      ),
    );
  });

  it("hides the owner control for own-pipeline callers", () => {
    render(
      <OpportunityCreateSheet
        workspaceId="ws-1"
        pipelineId="pipeline-1"
        stages={stages}
        defaultStageId="stage-1"
        contactId={42}
        contact={{ id: 42, first_name: "Helen", last_name: "Vasquez" }}
        canAssignOwners={false}
        open
        onOpenChange={vi.fn()}
      />,
      { wrapper: QueryWrapper },
    );

    expect(screen.queryByRole("combobox", { name: "Owner" })).not.toBeInTheDocument();
  });

  it("lets a manager reassign from the detail sheet", async () => {
    render(
      <OpportunityDetailSheet
        workspaceId="ws-1"
        opportunityId="opportunity-1"
        stages={stages}
        canAssignOwners
        open
        onOpenChange={vi.fn()}
      />,
      { wrapper: QueryWrapper },
    );

    await screen.findByText("Roof replacement");
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Owner" }), "7");

    await waitFor(() =>
      expect(updateMock).toHaveBeenCalledWith("ws-1", "opportunity-1", {
        assigned_user_id: 7,
      }),
    );
  });

  it("shows historical ownership on the card", () => {
    render(<OpportunityCardSummary opportunity={opportunity} />);

    expect(screen.getByText("Owner: Avery Owner")).toBeInTheDocument();
  });
});
