import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ContactOpportunities } from "@/components/contacts/contact-sidebar/contact-opportunities";
import type { Contact, Opportunity, Pipeline } from "@/types";

const { listMock, listPipelinesMock, createMock, toastMock } = vi.hoisted(() => ({
  listMock: vi.fn(),
  listPipelinesMock: vi.fn(),
  createMock: vi.fn(),
  toastMock: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/lib/api/opportunities", () => ({
  opportunitiesApi: {
    list: listMock,
    listPipelines: listPipelinesMock,
    create: createMock,
  },
}));

vi.mock("@/providers/workspace-provider", () => ({
  useWorkspace: () => ({ currentWorkspace: { role: "owner" } }),
}));

vi.mock("@/components/workspaces/team-member-picker", () => ({
  TeamMemberPicker: () => null,
}));

vi.mock("sonner", () => ({ toast: toastMock }));

const pipeline: Pipeline = {
  id: "pipeline-1",
  workspace_id: "ws-1",
  name: "Sales",
  is_active: true,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
  stages: [
    {
      id: "stage-2",
      pipeline_id: "pipeline-1",
      name: "Quoted",
      order: 1,
      probability: 60,
      stage_type: "active",
      created_at: "2026-08-01T00:00:00Z",
      updated_at: "2026-08-01T00:00:00Z",
    },
    {
      id: "stage-1",
      pipeline_id: "pipeline-1",
      name: "New lead",
      order: 0,
      probability: 10,
      stage_type: "active",
      created_at: "2026-08-01T00:00:00Z",
      updated_at: "2026-08-01T00:00:00Z",
    },
  ],
};

const contact: Contact = {
  id: 7039,
  user_id: 1,
  workspace_id: "ws-1",
  first_name: "Lisa",
  last_name: "Shelton",
  company_name: "Shelton Homes",
  status: "qualified",
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

const existingDeal: Opportunity = {
  id: "opportunity-1",
  workspace_id: "ws-1",
  pipeline_id: "pipeline-1",
  stage_id: "stage-2",
  primary_contact_id: 7039,
  name: "Lisa Shelton — Shelton Homes",
  status: "open",
  probability: 60,
  amount: 2400,
  currency: "USD",
  is_active: true,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

let queryClient: QueryClient;

function QueryWrapper({ children }: { children: React.ReactNode }) {
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

function renderPanel() {
  return render(<ContactOpportunities workspaceId="ws-1" contact={contact} />, {
    wrapper: QueryWrapper,
  });
}

describe("contact opportunities panel", () => {
  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    vi.clearAllMocks();
    listMock.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 });
    listPipelinesMock.mockResolvedValue([pipeline]);
    createMock.mockResolvedValue(existingDeal);
  });

  it("asks only for this contact's deals", async () => {
    renderPanel();

    await waitFor(() =>
      expect(listMock).toHaveBeenCalledWith(
        "ws-1",
        expect.objectContaining({ contact_id: 7039 }),
      ),
    );
  });

  it("shows the deals this contact is already on, with stage and amount", async () => {
    listMock.mockResolvedValue({
      items: [existingDeal],
      total: 1,
      page: 1,
      page_size: 20,
    });

    renderPanel();

    expect(await screen.findByText("Lisa Shelton — Shelton Homes")).toBeInTheDocument();
    expect(await screen.findByText(/Quoted/)).toBeInTheDocument();
    expect(screen.getByText(/\$2,400/)).toBeInTheDocument();
    // Already on the board: the button must not read like a first add.
    expect(
      await screen.findByRole("button", { name: "Add another deal" }),
    ).toBeInTheDocument();
  });

  it("creates a deal linked to the contact, in the first stage", async () => {
    renderPanel();

    await userEvent.click(
      await screen.findByRole("button", { name: "Add to pipeline" }),
    );

    // Name pre-fills from the contact so the card is identifiable on the board.
    expect(await screen.findByLabelText("Name *")).toHaveValue(
      "Lisa Shelton — Shelton Homes",
    );

    await userEvent.click(screen.getByRole("button", { name: "Create Opportunity" }));

    await waitFor(() =>
      expect(createMock).toHaveBeenCalledWith(
        "ws-1",
        expect.objectContaining({
          primary_contact_id: 7039,
          pipeline_id: "pipeline-1",
          stage_id: "stage-1",
          name: "Lisa Shelton — Shelton Homes",
        }),
      ),
    );
  });

  it("ignores deals belonging to other contacts", async () => {
    // An API that drops the contact_id filter (older backend, or a regression)
    // returns the whole board; the panel must not claim those as this lead's.
    listMock.mockResolvedValue({
      items: [existingDeal, { ...existingDeal, id: "opportunity-2", primary_contact_id: 999, name: "Someone else's roof" }],
      total: 2,
      page: 1,
      page_size: 20,
    });

    renderPanel();

    expect(await screen.findByText("Lisa Shelton — Shelton Homes")).toBeInTheDocument();
    expect(screen.queryByText("Someone else's roof")).not.toBeInTheDocument();
  });

  it("says so when the workspace has no pipeline yet", async () => {
    listPipelinesMock.mockResolvedValue([]);

    renderPanel();

    expect(await screen.findByText(/No pipeline yet/)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Add to pipeline" }),
    ).not.toBeInTheDocument();
  });
});
