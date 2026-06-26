import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LeadSourcesSettingsTab } from "@/components/settings/lead-sources-settings-tab";
import type { LeadSource } from "@/lib/api/lead-sources";

const { listMock, createMock, updateMock, deleteMock, useWorkspaceIdMock } =
  vi.hoisted(() => ({
    listMock: vi.fn(),
    createMock: vi.fn(),
    updateMock: vi.fn(),
    deleteMock: vi.fn(),
    useWorkspaceIdMock: vi.fn(),
  }));

vi.mock("@/lib/api/lead-sources", () => ({
  leadSourcesApi: {
    list: listMock,
    create: createMock,
    update: updateMock,
    delete: deleteMock,
  },
}));

vi.mock("@/hooks/useWorkspaceId", () => ({
  useWorkspaceId: () => useWorkspaceIdMock(),
}));

// The autopilot card fetches workspace settings; it's irrelevant to this tab.
vi.mock("@/components/settings/outbound-autopilot-card", () => ({
  OutboundAutopilotCard: () => null,
}));

function source(overrides: Partial<LeadSource> = {}): LeadSource {
  return {
    id: "src-1",
    workspace_id: "ws-1",
    name: "Pricing Page Leads",
    public_key: "pk_1",
    allowed_domains: ["example.com"],
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

function renderTab() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  render(
    <QueryClientProvider client={client}>
      <LeadSourcesSettingsTab />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  useWorkspaceIdMock.mockReturnValue("ws-1");
});

describe("LeadSourcesSettingsTab", () => {
  it("labels each source with its acquisition channel", async () => {
    listMock.mockResolvedValue([
      source({ id: "fb", name: "FB Promo", source_type: "facebook_ads" }),
      source({ id: "g", name: "Search Ads", source_type: "google_ads" }),
    ]);

    renderTab();

    expect(await screen.findByText("FB Promo")).toBeInTheDocument();
    expect(screen.getByText("Search Ads")).toBeInTheDocument();
    // Channel badges derived from source_type.
    expect(screen.getByText("Facebook Ads")).toBeInTheDocument();
    expect(screen.getByText("Google Ads")).toBeInTheDocument();
  });

  it("shows the empty state when there are no sources", async () => {
    listMock.mockResolvedValue([]);

    renderTab();

    expect(await screen.findByText("No lead sources yet")).toBeInTheDocument();
  });

  it("creates a source with the selected channel in the API payload", async () => {
    listMock.mockResolvedValue([]);
    createMock.mockResolvedValue(source());

    renderTab();

    await screen.findByText("No lead sources yet");
    await userEvent.click(screen.getByRole("button", { name: /add source/i }));

    await userEvent.type(
      await screen.findByLabelText("Name"),
      "Pricing Page Leads",
    );

    // Pick the acquisition channel via the reusable SourceTypePicker.
    await userEvent.click(screen.getByRole("combobox", { name: "Channel" }));
    await userEvent.click(
      await screen.findByRole("option", { name: "Facebook Ads" }),
    );

    await userEvent.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() =>
      expect(createMock).toHaveBeenCalledWith(
        "ws-1",
        expect.objectContaining({
          name: "Pricing Page Leads",
          source_type: "facebook_ads",
          action: "collect",
        }),
      ),
    );
  });
});
