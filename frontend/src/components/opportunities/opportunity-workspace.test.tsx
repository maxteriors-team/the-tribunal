import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OpportunityWorkspace } from "@/components/opportunities/opportunity-workspace";
import type { Contact, Opportunity, Pipeline } from "@/types";

const {
  getMock,
  listPipelinesMock,
  updateMock,
  setInstallationDateMock,
  pushMock,
  replaceMock,
  navigation,
  contactState,
} = vi.hoisted(() => ({
  getMock: vi.fn(),
  listPipelinesMock: vi.fn(),
  updateMock: vi.fn(),
  setInstallationDateMock: vi.fn(),
  pushMock: vi.fn(),
  replaceMock: vi.fn(),
  navigation: { search: "" },
  contactState: {
    data: undefined as Contact | undefined,
    isPending: false,
    isError: false,
  },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock, replace: replaceMock }),
  useSearchParams: () => new URLSearchParams(navigation.search),
}));
vi.mock("@/hooks/useWorkspaceId", () => ({ useWorkspaceId: () => "workspace-1" }));
vi.mock("@/hooks/useCapabilities", () => ({
  useCapabilities: () => ({ can: () => true }),
}));
vi.mock("@/hooks/useContacts", () => ({ useContact: () => contactState }));
vi.mock("@/lib/api/opportunities", () => ({
  opportunitiesApi: {
    get: getMock,
    listPipelines: listPipelinesMock,
    update: updateMock,
    setInstallationDate: setInstallationDateMock,
  },
}));
vi.mock("@/components/opportunities/opportunity-followups", () => ({
  OpportunityFollowups: () => <div>Deal follow-up controls</div>,
}));
vi.mock("@/components/conversation/conversation-feed", () => ({
  ConversationFeed: ({ contact }: { contact: Contact }) => (
    <div data-testid="deal-conversation">Conversation for {contact.first_name}</div>
  ),
}));
vi.mock("@/components/ui/contact-combobox", () => ({
  ContactPicker: () => <div data-testid="customer-picker" />,
}));
vi.mock("@/components/workspaces/team-member-picker", () => ({
  TeamMemberPicker: ({
    value,
    onValueChange,
    label,
  }: {
    value: number | null;
    onValueChange: (value: number | null) => void;
    label: string;
  }) => (
    <select
      aria-label={label}
      value={value ?? ""}
      onChange={(event) => onValueChange(event.target.value ? Number(event.target.value) : null)}
    >
      <option value="">Unassigned</option>
      <option value="7">Dana Rep</option>
    </select>
  ),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const contact: Contact = {
  id: 42,
  user_id: 1,
  workspace_id: "workspace-1",
  first_name: "Helen",
  last_name: "Vasquez",
  email: "helen@example.com",
  phone_number: "+15551234567",
  status: "qualified",
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

const opportunity: Opportunity = {
  id: "opportunity-1",
  workspace_id: "workspace-1",
  pipeline_id: "pipeline-1",
  stage_id: "stage-1",
  name: "Roof replacement",
  amount: 4200,
  currency: "USD",
  probability: 40,
  status: "open",
  description: "Replace the weathered north slope.",
  source: "referral",
  assigned_user_id: 4,
  assignee: { id: 4, full_name: "Avery Owner", email: "avery@example.com" },
  primary_contact_id: 42,
  primary_contact: {
    id: 42,
    first_name: "Helen",
    last_name: "Vasquez",
    full_name: "Helen Vasquez",
    email: "helen@example.com",
    phone_number: "+15551234567",
    status: "qualified",
  },
  tasks: [],
  activities: [
    {
      id: "activity-install",
      opportunity_id: "opportunity-1",
      activity_type: "installation_scheduled",
      new_value: "2026-09-15",
      created_at: "2026-09-01T10:00:00Z",
    },
    {
      id: "activity-call",
      opportunity_id: "opportunity-1",
      activity_type: "call",
      description: "Customer approved the revised scope.",
      new_value: "completed",
      created_at: "2026-09-01T09:00:00Z",
    },
  ],
  is_active: true,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-09-01T10:00:00Z",
};

const pipeline: Pipeline = {
  id: "pipeline-1",
  workspace_id: "workspace-1",
  name: "Sales pipeline",
  is_active: true,
  stages: [
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
  ],
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

function renderWorkspace() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <OpportunityWorkspace opportunityId="opportunity-1" />
    </QueryClientProvider>,
  );
}

describe("OpportunityWorkspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    navigation.search = "";
    contactState.data = contact;
    contactState.isPending = false;
    contactState.isError = false;
    getMock.mockResolvedValue(opportunity);
    listPipelinesMock.mockResolvedValue([pipeline]);
    updateMock.mockResolvedValue(opportunity);
    setInstallationDateMock.mockResolvedValue({ installation_date: "2026-10-02" });
  });

  it("keeps notes and the linked SMS thread inside the routed deal", async () => {
    navigation.search = "contact=42&owner=7";
    const user = userEvent.setup();
    renderWorkspace();

    expect(await screen.findByRole("heading", { name: "Roof replacement" })).toBeVisible();
    expect(screen.getByText("Deal follow-up controls")).toBeVisible();
    expect(screen.getByRole("link", { name: /Back to pipeline/ })).toHaveAttribute(
      "href",
      "/opportunities?contact=42&owner=7",
    );

    await user.click(screen.getByRole("tab", { name: "SMS" }));

    expect(screen.getByTestId("deal-conversation")).toHaveTextContent("Conversation for Helen");
    expect(replaceMock).toHaveBeenCalledWith(
      "/opportunities/opportunity-1?contact=42&owner=7&tab=sms",
      { scroll: false },
    );
  });

  it("handles a deal with no linked customer without mounting a conversation", async () => {
    getMock.mockResolvedValue({
      ...opportunity,
      primary_contact_id: null,
      primary_contact: null,
    });
    contactState.data = undefined;
    const user = userEvent.setup();
    renderWorkspace();

    await user.click(await screen.findByRole("tab", { name: "SMS" }));

    expect(
      screen.getByText("Link a customer in Deal details before sending a text."),
    ).toBeVisible();
    expect(screen.queryByTestId("deal-conversation")).not.toBeInTheDocument();
  });

  it("reassigns the deal from the full-page controls", async () => {
    const user = userEvent.setup();
    renderWorkspace();

    await user.selectOptions(await screen.findByRole("combobox", { name: "Owner" }), "7");

    await waitFor(() =>
      expect(updateMock).toHaveBeenCalledWith("workspace-1", "opportunity-1", {
        assigned_user_id: 7,
      }),
    );
  });

  it("saves the structured installation date on the deal", async () => {
    const user = userEvent.setup();
    renderWorkspace();

    const date = await screen.findByLabelText("Installation date");
    expect(date).toHaveValue("2026-09-15");
    await user.clear(date);
    await user.type(date, "2026-10-02");
    await user.click(screen.getByRole("button", { name: "Save installation date" }));

    await waitFor(() =>
      expect(setInstallationDateMock).toHaveBeenCalledWith("workspace-1", "opportunity-1", {
        installation_date: "2026-10-02",
      }),
    );
  });

  it("offers retry when the deal cannot load", async () => {
    getMock.mockRejectedValue(new Error("offline"));
    renderWorkspace();

    expect(await screen.findByText("Couldn't load this deal.")).toBeVisible();
    expect(screen.getByRole("button", { name: /try again/i })).toBeEnabled();
  });
});
