"use client";

import { useQuery } from "@tanstack/react-query";

import { agentsApi } from "@/lib/api/agents";
import { queryKeys } from "@/lib/query-keys";
import { STATIC } from "@/lib/query-options";
import { useWorkspace } from "@/providers/workspace-provider";

export interface SetupStatus {
  /** Workspace/agent probe still resolving — callers should wait before acting. */
  isLoading: boolean;
  /** The current workspace has no AI agent yet, i.e. onboarding never finished. */
  needsSetup: boolean;
  workspaceId: string | null;
}

/**
 * Cheap "is this workspace configured?" probe for finding RF-002.
 *
 * The onboarding wizard's final step creates the workspace's first AI
 * agent, so "zero agents" is a reliable, already-available signal that a
 * brand-new / unconfigured workspace has never completed setup. We fetch a
 * single-row page so the probe stays light.
 *
 * Errors are treated conservatively as "configured" so a transient API hiccup
 * never force-redirects an established workspace into the wizard.
 */
export function useSetupStatus(): SetupStatus {
  const { currentWorkspaceId, isPending: workspacePending } = useWorkspace();

  const { data, isPending, isError } = useQuery({
    queryKey: queryKeys.agents.list(currentWorkspaceId ?? "", { page_size: 1 }),
    queryFn: () => agentsApi.list(currentWorkspaceId!, { page: 1, page_size: 1 }),
    enabled: !!currentWorkspaceId,
    ...STATIC,
  });

  const agentsLoading = !!currentWorkspaceId && isPending;
  const isLoading = workspacePending || agentsLoading;

  const needsSetup =
    !!currentWorkspaceId &&
    !isLoading &&
    !isError &&
    data !== undefined &&
    (data.total ?? 0) === 0;

  return { isLoading, needsSetup, workspaceId: currentWorkspaceId };
}
