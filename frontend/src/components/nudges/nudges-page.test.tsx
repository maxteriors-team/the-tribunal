import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { NudgesPage } from "@/components/nudges/nudges-page";
import { queryKeys } from "@/lib/query-keys";
import type { HumanNudge } from "@/types/nudge";

const { clearAllMock, getStatsMock, listMock, toastSuccessMock } = vi.hoisted(() => ({
  clearAllMock: vi.fn(),
  getStatsMock: vi.fn(),
  listMock: vi.fn(),
  toastSuccessMock: vi.fn(),
}));

vi.mock("@/hooks/useWorkspaceId", () => ({ useWorkspaceId: () => "ws-1" }));

vi.mock("@/lib/api/nudges", () => ({
  nudgesApi: {
    act: vi.fn(),
    clearAll: clearAllMock,
    dismiss: vi.fn(),
    getStats: getStatsMock,
    list: listMock,
    snooze: vi.fn(),
  },
}));

vi.mock("sonner", () => ({
  toast: { error: vi.fn(), success: toastSuccessMock },
}));

const nudge: HumanNudge = {
  id: "nudge-1",
  workspace_id: "ws-1",
  contact_id: 1,
  nudge_type: "follow_up",
  title: "Follow up",
  message: "Call this lead",
  suggested_action: "call",
  priority: "medium",
  due_date: "2026-08-24T12:00:00Z",
  source_date_field: null,
  status: "pending",
  snoozed_until: null,
  delivered_via: null,
  delivered_at: null,
  acted_at: null,
  assigned_to_user_id: 11,
  created_at: "2026-08-24T12:00:00Z",
  contact_name: "Ada Lead",
  contact_phone: null,
  contact_company: null,
};

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
  });
  const invalidateSpy = vi.spyOn(client, "invalidateQueries");
  render(
    <QueryClientProvider client={client}>
      <NudgesPage />
    </QueryClientProvider>,
  );
  return invalidateSpy;
}

describe("NudgesPage Clear All", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getStatsMock.mockResolvedValue({
      pending: 1,
      sent: 1,
      acted: 0,
      dismissed: 0,
      snoozed: 0,
      total: 2,
    });
    listMock.mockResolvedValue({ items: [nudge], total: 1, page: 1, page_size: 20 });
  });

  it("hides Clear All when no active visible nudges exist", async () => {
    getStatsMock.mockResolvedValue({
      pending: 0,
      sent: 0,
      acted: 1,
      dismissed: 1,
      snoozed: 0,
      total: 2,
    });
    listMock.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 });

    renderPage();

    await screen.findByText("All caught up!");
    expect(screen.queryByRole("button", { name: "Clear All" })).not.toBeInTheDocument();
  });

  it("requires confirmation before clearing", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    renderPage();

    await userEvent.click(await screen.findByRole("button", { name: "Clear All" }));

    expect(window.confirm).toHaveBeenCalledOnce();
    expect(clearAllMock).not.toHaveBeenCalled();
  });

  it("submits once, disables while pending, toasts the count, and refreshes workspace nudges", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    let resolveClearAll!: (value: { dismissed_count: number }) => void;
    clearAllMock.mockImplementation(
      () =>
        new Promise<{ dismissed_count: number }>((resolve) => {
          resolveClearAll = resolve;
        }),
    );
    const invalidateSpy = renderPage();
    const user = userEvent.setup();

    const button = await screen.findByRole("button", { name: "Clear All" });
    await user.click(button);

    expect(clearAllMock).toHaveBeenCalledOnce();
    expect(screen.getByRole("button", { name: "Clearing..." })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Clearing..." }));
    expect(clearAllMock).toHaveBeenCalledOnce();

    resolveClearAll({ dismissed_count: 2 });

    await waitFor(() => expect(toastSuccessMock).toHaveBeenCalledWith("Dismissed 2 nudges"));
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: queryKeys.nudges.all("ws-1"),
    });
  });
});
