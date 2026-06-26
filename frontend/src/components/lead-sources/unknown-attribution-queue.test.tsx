import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { UnknownAttributionQueue } from "@/components/lead-sources/unknown-attribution-queue";
import type {
  LeadSource,
  UnattributedLead,
} from "@/lib/api/lead-sources";

const { listMock, listUnattributedMock, assignSourceMock } = vi.hoisted(() => ({
  listMock: vi.fn(),
  listUnattributedMock: vi.fn(),
  assignSourceMock: vi.fn(),
}));

vi.mock("@/lib/api/lead-sources", () => ({
  leadSourcesApi: {
    list: listMock,
    listUnattributed: listUnattributedMock,
    assignSource: assignSourceMock,
  },
}));

function source(overrides: Partial<LeadSource> = {}): LeadSource {
  return {
    id: "src-fb",
    workspace_id: "ws-1",
    name: "Facebook Ads",
    public_key: "pk_1",
    allowed_domains: [],
    enabled: true,
    source_type: "facebook_ads",
    action: "collect",
    action_config: {},
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    endpoint_url: "https://api.test/lead-sources/pk_1",
    ...overrides,
  };
}

function lead(overrides: Partial<UnattributedLead> = {}): UnattributedLead {
  return {
    contact_id: 1,
    first_name: "Dana",
    last_name: "Lane",
    phone_number: "+15558675309",
    email: null,
    source: null,
    created_at: "2026-01-02T00:00:00Z",
    suggested_source_type: null,
    suggested_lead_source_id: null,
    ...overrides,
  };
}

function renderQueue() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  render(
    <QueryClientProvider client={client}>
      <UnknownAttributionQueue workspaceId="ws-1" />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  listMock.mockResolvedValue([source()]);
});

describe("UnknownAttributionQueue", () => {
  it("lists leads that need a source with an actionable count", async () => {
    listUnattributedMock.mockResolvedValue([
      lead({ contact_id: 1, first_name: "Dana", last_name: "Lane" }),
      lead({ contact_id: 2, first_name: "Sam", last_name: "Cole" }),
    ]);

    renderQueue();

    expect(await screen.findByText("Dana Lane")).toBeInTheDocument();
    expect(screen.getByText("Sam Cole")).toBeInTheDocument();
    expect(screen.getByText("2 leads need a source")).toBeInTheDocument();
  });

  it("shows an all-clear empty state when nothing is unattributed", async () => {
    listUnattributedMock.mockResolvedValue([]);

    renderQueue();

    expect(await screen.findByText("All leads attributed")).toBeInTheDocument();
  });

  it("surfaces an error+retry state when the queue fails to load", async () => {
    listUnattributedMock.mockRejectedValue(new Error("boom"));

    renderQueue();

    expect(
      await screen.findByRole("button", { name: /try again/i }),
    ).toBeInTheDocument();
  });

  it("assigns the picked source to a lead", async () => {
    listUnattributedMock.mockResolvedValue([lead()]);
    assignSourceMock.mockResolvedValue(undefined);

    renderQueue();

    await screen.findByText("Dana Lane");

    // Assign is disabled until a source is chosen.
    const assignButton = screen.getByRole("button", { name: "Assign" });
    expect(assignButton).toBeDisabled();

    await userEvent.click(
      screen.getByRole("combobox", { name: "Assign source for Dana Lane" }),
    );
    await userEvent.click(await screen.findByRole("option", { name: "Facebook Ads" }));

    expect(assignButton).toBeEnabled();
    await userEvent.click(assignButton);

    await waitFor(() =>
      expect(assignSourceMock).toHaveBeenCalledWith("ws-1", 1, {
        lead_source_id: "src-fb",
      }),
    );
  });
});
