import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OpportunitiesBoard } from "@/components/opportunities/opportunities-board";
import type { Opportunity, Pipeline } from "@/types";

const { listMock, listPipelinesMock, getActiveTeamMembersMock } = vi.hoisted(() => ({
  listMock: vi.fn(),
  listPipelinesMock: vi.fn(),
  getActiveTeamMembersMock: vi.fn(),
}));

vi.mock("@/hooks/useWorkspaceId", () => ({ useWorkspaceId: () => "workspace-1" }));
vi.mock("@/providers/workspace-provider", () => ({
  useWorkspace: () => ({ currentWorkspace: { role: "owner" } }),
}));
vi.mock("@/hooks/useContacts", () => ({ useContact: () => ({ data: null }) }));
vi.mock("@/hooks/useOutboundCall", () => ({
  useOutboundCall: () => ({
    callTarget: null,
    callDialogOpen: false,
    setCallDialogOpen: vi.fn(),
    startCall: vi.fn(),
    submitCall: vi.fn(),
    initiateCallMutation: { isPending: false },
  }),
}));
vi.mock("@/lib/api/opportunities", () => ({
  opportunitiesApi: {
    list: listMock,
    listPipelines: listPipelinesMock,
    removeFromPipeline: vi.fn(),
    update: vi.fn(),
  },
}));
vi.mock("@/lib/api/settings", () => ({
  settingsApi: { getActiveTeamMembers: getActiveTeamMembersMock },
}));
vi.mock("@/components/ui/contact-combobox", () => ({ ContactPicker: () => <div /> }));
vi.mock("@/components/calls/outbound-call-dialog", () => ({ OutboundCallDialog: () => null }));
vi.mock("@/components/contacts/schedule-appointment-dialog", () => ({
  ScheduleAppointmentDialog: () => null,
}));
vi.mock("@/components/opportunities/manage-stages-dialog", () => ({
  ManageStagesDialog: () => null,
}));
vi.mock("@/components/opportunities/opportunity-create-sheet", () => ({
  OpportunityCreateSheet: () => null,
}));
vi.mock("@/components/opportunities/opportunity-detail-sheet", () => ({
  OpportunityDetailSheet: () => null,
}));
vi.mock("@/components/opportunities/opportunity-card", () => ({
  OpportunityCard: ({ opportunity }: { opportunity: Opportunity }) => (
    <article>{opportunity.name}</article>
  ),
  OpportunityCardSummary: () => null,
}));

const pipeline: Pipeline = {
  id: "pipeline-1",
  workspace_id: "workspace-1",
  name: "Sales pipeline",
  is_active: true,
  stages: [
    {
      id: "stage-1",
      pipeline_id: "pipeline-1",
      name: "New",
      order: 0,
      probability: 10,
      stage_type: "active",
      created_at: "2026-08-01T00:00:00Z",
      updated_at: "2026-08-01T00:00:00Z",
    },
    {
      id: "stage-2",
      pipeline_id: "pipeline-1",
      name: "Won",
      order: 1,
      probability: 100,
      stage_type: "won",
      created_at: "2026-08-01T00:00:00Z",
      updated_at: "2026-08-01T00:00:00Z",
    },
  ],
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

const opportunity: Opportunity = {
  id: "opportunity-1",
  workspace_id: "workspace-1",
  pipeline_id: "pipeline-1",
  stage_id: "stage-1",
  name: "Roof replacement",
  currency: "USD",
  probability: 10,
  status: "open",
  is_active: true,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

describe("OpportunitiesBoard scrolling", () => {
  beforeEach(() => {
    listPipelinesMock.mockResolvedValue([pipeline]);
    listMock.mockResolvedValue({ items: [opportunity], total: 1, page: 1, page_size: 200, pages: 1 });
    getActiveTeamMembersMock.mockResolvedValue([
      { id: 7, full_name: "Dana Rep", email: "dana@example.com", role: "sales_rep" },
    ]);
  });

  it("keeps horizontal stages and every vertical card list independently accessible", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <OpportunitiesBoard />
      </QueryClientProvider>,
    );

    const horizontalViewport = await screen.findByRole("region", {
      name: "Opportunity stages, scroll horizontally",
    });
    const stageColumns = [screen.getByTestId("stage-column-stage-1"), screen.getByTestId("stage-column-stage-2")];
    const cardLists = document.querySelectorAll('[data-slot="opportunity-stage-scroll"]');

    expect(horizontalViewport).toHaveAttribute("tabindex", "0");
    expect(horizontalViewport).toHaveClass("h-full", "overflow-y-hidden");
    expect(horizontalViewport.parentElement).toHaveClass("min-h-0", "flex-1");
    expect(stageColumns).toHaveLength(2);
    for (const column of stageColumns) expect(column).toHaveClass("h-full", "min-h-0");
    expect(cardLists).toHaveLength(2);
    for (const list of cardLists) expect(list).toHaveClass("min-h-0", "overflow-y-auto");
    expect(screen.getByText("Roof replacement")).toBeInTheDocument();
  });

  it("asks the server for one rep's deals once a rep is picked", async () => {
    const user = userEvent.setup();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <OpportunitiesBoard />
      </QueryClientProvider>,
    );

    // Unfiltered board must not narrow the query to anyone.
    await screen.findByTestId("opportunity-rep-filter");
    expect(listMock).toHaveBeenCalledWith(
      "workspace-1",
      expect.objectContaining({ owner_id: undefined }),
    );

    await user.click(screen.getByTestId("opportunity-rep-filter"));
    await user.click(await screen.findByRole("option", { name: "Dana Rep" }));

    await waitFor(() =>
      expect(listMock).toHaveBeenCalledWith("workspace-1", expect.objectContaining({ owner_id: 7 })),
    );
  });
});
