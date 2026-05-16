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

beforeEach(() => {
  listMock.mockReset();
  useAuthMock.mockReset();
  window.localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
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

  it("falls back to the default workspace when no stored id is present", async () => {
    useAuthMock.mockReturnValue({ isAuthenticated: true, user: null });
    listMock.mockResolvedValue(WORKSPACES);

    renderWithProviders();

    await waitFor(() => {
      expect(screen.getByTestId("current").textContent).toBe("ws_b");
    });
    expect(window.localStorage.getItem("current_workspace_id")).toBe("ws_b");
  });

  it("restores the stored workspace id when it matches a member workspace", async () => {
    window.localStorage.setItem("current_workspace_id", "ws_c");
    useAuthMock.mockReturnValue({ isAuthenticated: true, user: null });
    listMock.mockResolvedValue(WORKSPACES);

    renderWithProviders();

    await waitFor(() => {
      expect(screen.getByTestId("current").textContent).toBe("ws_c");
    });
  });

  it("ignores a stale stored id and picks the default instead", async () => {
    window.localStorage.setItem("current_workspace_id", "ws_gone");
    useAuthMock.mockReturnValue({ isAuthenticated: true, user: null });
    listMock.mockResolvedValue(WORKSPACES);

    renderWithProviders();

    await waitFor(() => {
      expect(screen.getByTestId("current").textContent).toBe("ws_b");
    });
    expect(window.localStorage.getItem("current_workspace_id")).toBe("ws_b");
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
    expect(window.localStorage.getItem("current_workspace_id")).toBe("ws_c");
    expect(clearSpy).toHaveBeenCalled();
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
