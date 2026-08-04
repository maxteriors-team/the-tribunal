import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { WorkspaceWithMembership } from "@/lib/api/workspaces";
import { WorkspaceProvider, useWorkspace } from "@/providers/workspace-provider";

// --- Hoisted mocks -------------------------------------------------------

const { listMock, useAuthMock } = vi.hoisted(() => ({
  listMock: vi.fn<() => Promise<WorkspaceWithMembership[]>>(),
  useAuthMock: vi.fn(),
}));

vi.mock("@/lib/api/workspaces", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/workspaces")>(
    "@/lib/api/workspaces",
  );
  return {
    ...actual,
    workspacesApi: { ...actual.workspacesApi, list: listMock },
  };
});

vi.mock("@/providers/auth-provider", () => ({
  useAuth: () => useAuthMock(),
}));

// --- Fixtures ------------------------------------------------------------

const makeWorkspace = (
  id: string,
  overrides: Partial<WorkspaceWithMembership> = {},
): WorkspaceWithMembership => ({
  workspace: {
    id,
    name: `ws-${id}`,
    slug: `ws-${id}`,
    description: null,
    settings: {},
    is_active: true,
    onboarding_completed_at: "2026-01-01T00:00:00Z",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  },
  role: "owner",
  is_default: false,
  ...overrides,
});

const WORKSPACES: WorkspaceWithMembership[] = [
  makeWorkspace("ws_a"),
  makeWorkspace("ws_b", { is_default: true }),
  makeWorkspace("ws_c"),
];

// --- Harness -------------------------------------------------------------

function Probe() {
  const { currentWorkspaceId, workspaces, setCurrentWorkspace, isPending } =
    useWorkspace();
  return (
    <div>
      <div data-testid="pending">{isPending ? "yes" : "no"}</div>
      <div data-testid="current">{currentWorkspaceId ?? "none"}</div>
      <div data-testid="count">{workspaces.length}</div>
      <button onClick={() => setCurrentWorkspace("ws_c")}>switch</button>
    </div>
  );
}

function renderWithProviders(client?: QueryClient) {
  const queryClient =
    client ??
    new QueryClient({
      defaultOptions: {
        queries: { retry: false, gcTime: 0, staleTime: 0 },
      },
    });

  const utils = render(
    <QueryClientProvider client={queryClient}>
      <WorkspaceProvider>
        <Probe />
      </WorkspaceProvider>
    </QueryClientProvider>,
  );
  return { ...utils, queryClient };
}

// --- Setup ---------------------------------------------------------------

/** Where a *deliberate* workspace choice is remembered. */
const CHOICE_KEY = "current_workspace_choice";

/** Point `window.location.search` at `?workspace=<value>` for one test. */
function setWorkspaceParam(value: string): void {
  window.history.replaceState({}, "", `/?workspace=${value}`);
}

beforeEach(() => {
  listMock.mockReset();
  useAuthMock.mockReset();
  window.localStorage.clear();
  window.history.replaceState({}, "", "/");
});

afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
  window.history.replaceState({}, "", "/");
});

// --- Tests ---------------------------------------------------------------

describe("WorkspaceProvider", () => {
  it("does not fetch workspaces when unauthenticated", async () => {
    useAuthMock.mockReturnValue({ isAuthenticated: false, user: null });
    listMock.mockResolvedValue(WORKSPACES);

    renderWithProviders();

    await waitFor(() => {
      expect(screen.getByTestId("current").textContent).toBe("none");
    });
    expect(listMock).not.toHaveBeenCalled();
  });

  it("falls back to the default workspace when nothing was chosen", async () => {
    useAuthMock.mockReturnValue({ isAuthenticated: true, user: null });
    listMock.mockResolvedValue(WORKSPACES);

    renderWithProviders();

    await waitFor(() => {
      expect(screen.getByTestId("current").textContent).toBe("ws_b");
    });
    // Merely landing somewhere is not a choice, so nothing is recorded — the
    // server stays in charge of where this user opens.
    expect(window.localStorage.getItem(CHOICE_KEY)).toBeNull();
  });

  it("restores a deliberately chosen workspace", async () => {
    window.localStorage.setItem(CHOICE_KEY, "ws_c");
    useAuthMock.mockReturnValue({ isAuthenticated: true, user: null });
    listMock.mockResolvedValue(WORKSPACES);

    renderWithProviders();

    await waitFor(() => {
      expect(screen.getByTestId("current").textContent).toBe("ws_c");
    });
  });

  it("ignores a legacy remembered id and follows the server default", async () => {
    // `current_workspace_id` was rewritten on every resolution, so it recorded
    // wherever the user last *landed*. An invited teammate whose default was
    // corrected server-side kept reopening the workspace her browser had
    // memorised — which looked exactly like the invitation never working.
    window.localStorage.setItem("current_workspace_id", "ws_a");
    useAuthMock.mockReturnValue({ isAuthenticated: true, user: null });
    listMock.mockResolvedValue(WORKSPACES);

    renderWithProviders();

    await waitFor(() => {
      expect(screen.getByTestId("current").textContent).toBe("ws_b");
    });
  });

  it("drops a chosen workspace it can no longer reach", async () => {
    // Removed from that workspace, or it was deleted. Keeping it would shadow
    // the server default forever for something they cannot even open.
    window.localStorage.setItem(CHOICE_KEY, "ws_gone");
    useAuthMock.mockReturnValue({ isAuthenticated: true, user: null });
    listMock.mockResolvedValue(WORKSPACES);

    renderWithProviders();

    await waitFor(() => {
      expect(screen.getByTestId("current").textContent).toBe("ws_b");
    });
    await waitFor(() => {
      expect(window.localStorage.getItem(CHOICE_KEY)).toBeNull();
    });
  });

  it("falls back to the first workspace when none is marked default", async () => {
    useAuthMock.mockReturnValue({ isAuthenticated: true, user: null });
    listMock.mockResolvedValue([
      makeWorkspace("ws_only_a"),
      makeWorkspace("ws_only_b"),
    ]);

    renderWithProviders();

    await waitFor(() => {
      expect(screen.getByTestId("current").textContent).toBe("ws_only_a");
    });
  });

  it("switches the active workspace, persists it, and clears the query cache", async () => {
    useAuthMock.mockReturnValue({ isAuthenticated: true, user: null });
    listMock.mockResolvedValue(WORKSPACES);

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } },
    });
    const clearSpy = vi.spyOn(queryClient, "clear");

    renderWithProviders(queryClient);

    await waitFor(() => {
      expect(screen.getByTestId("current").textContent).toBe("ws_b");
    });

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "switch" }));

    expect(screen.getByTestId("current").textContent).toBe("ws_c");
    expect(window.localStorage.getItem(CHOICE_KEY)).toBe("ws_c");
    expect(clearSpy).toHaveBeenCalled();
  });

  it("honours ?workspace=<slug> so accepting an invitation lands in that workspace", async () => {
    // Accepting an invitation redirects to /?workspace=<slug>. An invitee who
    // already had a workspace of their own must land in the one they just
    // joined, not bounce back to a previous selection.
    window.localStorage.setItem(CHOICE_KEY, "ws_a");
    setWorkspaceParam("ws-ws_c");
    useAuthMock.mockReturnValue({ isAuthenticated: true, user: null });
    listMock.mockResolvedValue(WORKSPACES);

    renderWithProviders();

    await waitFor(() => {
      expect(screen.getByTestId("current").textContent).toBe("ws_c");
    });
    // ...and it sticks for the next visit, which carries no param: an explicit
    // hand-off link is as deliberate as clicking the switcher.
    await waitFor(() => {
      expect(window.localStorage.getItem(CHOICE_KEY)).toBe("ws_c");
    });
  });

  it("lets the switcher override a ?workspace= param", async () => {
    setWorkspaceParam("ws-ws_a");
    useAuthMock.mockReturnValue({ isAuthenticated: true, user: null });
    listMock.mockResolvedValue(WORKSPACES);

    renderWithProviders();

    await waitFor(() => {
      expect(screen.getByTestId("current").textContent).toBe("ws_a");
    });

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "switch" }));

    expect(screen.getByTestId("current").textContent).toBe("ws_c");
  });

  it("ignores a ?workspace= param that matches no member workspace", async () => {
    setWorkspaceParam("ws-not-mine");
    useAuthMock.mockReturnValue({ isAuthenticated: true, user: null });
    listMock.mockResolvedValue(WORKSPACES);

    renderWithProviders();

    await waitFor(() => {
      expect(screen.getByTestId("current").textContent).toBe("ws_b");
    });
  });

  it("opens the workspace a stranded teammate was finally added to", async () => {
    // The reported incident, end state. She was stranded for weeks in an empty
    // auto-provisioned workspace, so her browser had memorised it on every one
    // of those visits. Once her membership was corrected server-side, that
    // memory was the last thing still sending her back to the empty one — and
    // "the invite still doesn't work" is indistinguishable from the original bug.
    window.localStorage.setItem("current_workspace_id", "ws_stranded");
    useAuthMock.mockReturnValue({ isAuthenticated: true, user: null });
    listMock.mockResolvedValue([
      makeWorkspace("ws_stranded", { role: "owner" }),
      makeWorkspace("ws_real_team", { role: "admin", is_default: true }),
    ]);

    renderWithProviders();

    await waitFor(() => {
      expect(screen.getByTestId("current").textContent).toBe("ws_real_team");
    });
  });

  it("throws when useWorkspace is called outside the provider", () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    function Orphan() {
      useWorkspace();
      return null;
    }

    expect(() => render(<Orphan />)).toThrow(
      /useWorkspace must be used within a WorkspaceProvider/,
    );

    errorSpy.mockRestore();
  });
});
