"use client";

import { useWorkspace } from "@/providers/workspace-provider";

export interface SetupStatus {
  /** Workspace probe still resolving — callers should wait before acting. */
  isLoading: boolean;
  /** The operator has never completed onboarding for the current workspace. */
  needsSetup: boolean;
  workspaceId: string | null;
}

/**
 * "Has the operator configured this workspace?" (finding RF-002).
 *
 * Reads the workspace's explicit `onboarding_completed_at` stamp, written by the
 * backend only when the onboarding wizard actually completes.
 *
 * This deliberately does NOT count rows: setup state used to be inferred from
 * "zero AI agents", but `POST /workspaces` seeds a template agent at creation
 * time, so a UI-created workspace reported "configured" seconds after birth and
 * the gate below could never fire — while registration-created workspaces (no
 * seeded agent) always reported "needs setup". Same question, opposite answers,
 * decided purely by which code path created the workspace. A row the system
 * creates for the operator is not evidence the operator did anything.
 *
 * The stamp rides along on the workspace list the provider already fetches, so
 * this costs no extra request. A failed/absent workspace load leaves
 * `currentWorkspace` null and is treated conservatively as "configured", so a
 * transient API hiccup never force-redirects an established workspace into the
 * wizard.
 */
export function useSetupStatus(): SetupStatus {
  const {
    currentWorkspace,
    currentWorkspaceId,
    isPending: isLoading,
  } = useWorkspace();

  const needsSetup =
    !isLoading &&
    !!currentWorkspace &&
    !currentWorkspace.workspace.onboarding_completed_at;

  return { isLoading, needsSetup, workspaceId: currentWorkspaceId };
}
