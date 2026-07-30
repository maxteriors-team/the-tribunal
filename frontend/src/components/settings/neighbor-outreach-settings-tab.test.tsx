import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { NeighborOutreachSettingsTab } from "@/components/settings/neighbor-outreach-settings-tab";
import type { NeighborOutreachSettings } from "@/lib/api/settings";

/**
 * Neighbor-outreach settings.
 *
 * The tab has one job beyond saving numbers: make the legal shape of the feature
 * obvious. Print/canvass is the default channel, messaging is an opt-in that only
 * ever reaches already-consented contacts, and the search controls only appear
 * once the feature is on.
 */

const { getMock, updateMock, useWorkspaceIdMock } = vi.hoisted(() => ({
  getMock: vi.fn(),
  updateMock: vi.fn(),
  useWorkspaceIdMock: vi.fn(),
}));

vi.mock("@/lib/api/settings", () => ({
  settingsApi: {
    getNeighborOutreach: getMock,
    updateNeighborOutreach: updateMock,
  },
}));

vi.mock("@/hooks/useWorkspaceId", () => ({
  useWorkspaceId: () => useWorkspaceIdMock(),
}));

function settings(
  overrides: Partial<NeighborOutreachSettings> = {},
): NeighborOutreachSettings {
  return {
    enabled: true,
    radius_meters: 150,
    max_neighbors: 50,
    auto_generate_on_completion: true,
    message_template_id: null,
    allow_messaging: false,
    ...overrides,
  };
}

function renderTab() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  render(
    <QueryClientProvider client={client}>
      <NeighborOutreachSettingsTab />
    </QueryClientProvider>,
  );
}

describe("NeighborOutreachSettingsTab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useWorkspaceIdMock.mockReturnValue("ws-1");
    updateMock.mockImplementation(async (_ws: string, data: Partial<NeighborOutreachSettings>) =>
      settings(data),
    );
  });

  it("hides the search controls until the feature is enabled", async () => {
    getMock.mockResolvedValue(settings({ enabled: false }));
    renderTab();

    expect(await screen.findByLabelText("Enable neighbor outreach")).toBeInTheDocument();
    expect(screen.queryByLabelText("Radius (meters)")).not.toBeInTheDocument();
    expect(
      screen.queryByLabelText(/Allow SMS\/email to consented neighbors/),
    ).not.toBeInTheDocument();
  });

  it("shows the radius, cap, and auto-generate controls when enabled", async () => {
    getMock.mockResolvedValue(settings());
    renderTab();

    expect(await screen.findByLabelText("Radius (meters)")).toHaveValue(150);
    expect(screen.getByLabelText("Maximum neighbors per job")).toHaveValue(50);
    expect(screen.getByLabelText("Generate on job completion")).toBeChecked();
  });

  it("defaults messaging off and says why", async () => {
    getMock.mockResolvedValue(settings());
    renderTab();

    expect(
      await screen.findByLabelText(/Allow SMS\/email to consented neighbors/),
    ).not.toBeChecked();
    expect(
      screen.getByText(/A radius search returns addresses, not permission/),
    ).toBeInTheDocument();
  });

  it("saves a new radius on blur", async () => {
    const user = userEvent.setup();
    getMock.mockResolvedValue(settings());
    renderTab();

    const radius = await screen.findByLabelText("Radius (meters)");
    await user.clear(radius);
    await user.type(radius, "300");
    await user.tab();

    await waitFor(() => expect(updateMock).toHaveBeenCalledWith("ws-1", { radius_meters: 300 }));
  });

  it("does not save a radius the server would reject", async () => {
    const user = userEvent.setup();
    getMock.mockResolvedValue(settings());
    renderTab();

    const radius = await screen.findByLabelText("Radius (meters)");
    await user.clear(radius);
    await user.type(radius, "999999");
    await user.tab();

    expect(updateMock).not.toHaveBeenCalled();
  });

  it("toggles the messaging switch through the API", async () => {
    const user = userEvent.setup();
    getMock.mockResolvedValue(settings());
    renderTab();

    await user.click(
      await screen.findByLabelText(/Allow SMS\/email to consented neighbors/),
    );

    await waitFor(() =>
      expect(updateMock).toHaveBeenCalledWith("ws-1", { allow_messaging: true }),
    );
  });
});
