import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useSetupStatus } from "@/hooks/useSetupStatus";
import type { WorkspaceWithMembership } from "@/lib/api/workspaces";

const { useWorkspaceMock } = vi.hoisted(() => ({
  useWorkspaceMock: vi.fn(),
}));

vi.mock("@/providers/workspace-provider", () => ({
  useWorkspace: () => useWorkspaceMock(),
}));

function makeWorkspace(
  onboardingCompletedAt: string | null,
): WorkspaceWithMembership {
  return {
    workspace: {
      id: "ws-1",
      name: "QA Fresh Workspace Probe",
      slug: "qa-fresh-probe-001",
      description: null,
      settings: {},
      is_active: true,
      onboarding_completed_at: onboardingCompletedAt,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    },
    role: "owner",
    is_default: true,
  };
}

function mockWorkspaceContext(
  currentWorkspace: WorkspaceWithMembership | null,
  isPending = false,
) {
  useWorkspaceMock.mockReturnValue({
    workspaces: currentWorkspace ? [currentWorkspace] : [],
    currentWorkspace,
    currentWorkspaceId: currentWorkspace?.workspace.id ?? null,
    isPending,
    setCurrentWorkspace: vi.fn(),
  });
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("useSetupStatus", () => {
  it("offers onboarding to a workspace that was never onboarded", () => {
    // Regression: this workspace owns a seeded template agent from the moment
    // `POST /workspaces` created it. Counting agents reported "configured"
    // seconds after birth, so the setup banner, the "Finish setup" nav item and
    // the auto-redirect could never fire for any UI-created workspace.
    mockWorkspaceContext(makeWorkspace(null));

    const { result } = renderHook(() => useSetupStatus());

    expect(result.current.needsSetup).toBe(true);
    expect(result.current.isLoading).toBe(false);
    expect(result.current.workspaceId).toBe("ws-1");
  });

  it("treats a workspace as configured once onboarding stamped it", () => {
    mockWorkspaceContext(makeWorkspace("2026-02-01T12:00:00Z"));

    const { result } = renderHook(() => useSetupStatus());

    expect(result.current.needsSetup).toBe(false);
  });

  it("waits for the workspace probe instead of guessing while it loads", () => {
    mockWorkspaceContext(null, true);

    const { result } = renderHook(() => useSetupStatus());

    expect(result.current.isLoading).toBe(true);
    expect(result.current.needsSetup).toBe(false);
    expect(result.current.workspaceId).toBeNull();
  });

  it("fails closed to configured when no workspace resolves", () => {
    // A failed workspace load must never force an established workspace back
    // into the wizard.
    mockWorkspaceContext(null);

    const { result } = renderHook(() => useSetupStatus());

    expect(result.current.needsSetup).toBe(false);
  });
});
