"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { workspacesApi, type WorkspaceWithMembership } from "@/lib/api/workspaces";
import { queryKeys } from "@/lib/query-keys";
import { STATIC } from "@/lib/query-options";

import { useAuth } from "./auth-provider";

const WORKSPACE_STORAGE_KEY = "current_workspace_id";

interface WorkspaceContextType {
  workspaces: WorkspaceWithMembership[];
  currentWorkspace: WorkspaceWithMembership | null;
  currentWorkspaceId: string | null;
  isPending: boolean;
  setCurrentWorkspace: (workspaceId: string) => void;
}

const WorkspaceContext = createContext<WorkspaceContextType | undefined>(undefined);

function getStoredWorkspaceId(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return localStorage.getItem(WORKSPACE_STORAGE_KEY);
  } catch {
    return null;
  }
}

function setStoredWorkspaceId(workspaceId: string): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(WORKSPACE_STORAGE_KEY, workspaceId);
  } catch (error) {
    if (process.env.NODE_ENV !== "production") {
      console.error("Failed to save workspace ID:", error);
    }
  }
}

/**
 * Workspace requested via `?workspace=<slug|id>`.
 *
 * Accepting an invitation redirects to `/?workspace=<slug>`; without this the
 * param was inert and a member who already had their own workspace kept landing
 * back in it, making a successful join look like it had done nothing.
 */
function getRequestedWorkspaceParam(): string | null {
  if (typeof window === "undefined") return null;
  return new URLSearchParams(window.location.search).get("workspace");
}

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const { isAuthenticated } = useAuth();
  const queryClient = useQueryClient();
  // Holds an id *or* a slug: `?workspace=` arrives as a slug from the invitation
  // accept redirect, and is read once at mount so a later switcher choice (which
  // always sets a real id) cleanly overrides it.
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState<string | null>(
    () => getRequestedWorkspaceParam() ?? getStoredWorkspaceId()
  );

  const { data: workspaces = [], isPending } = useQuery({
    queryKey: queryKeys.workspaces.all(),
    queryFn: workspacesApi.list,
    enabled: isAuthenticated,
    ...STATIC,
  });

  const currentWorkspace = useMemo(() => {
    if (!isAuthenticated || workspaces.length === 0) return null;

    const selectedWorkspace = selectedWorkspaceId
      ? workspaces.find(
          (w) =>
            w.workspace.id === selectedWorkspaceId ||
            w.workspace.slug === selectedWorkspaceId
        )
      : null;

    return selectedWorkspace ?? workspaces.find((w) => w.is_default) ?? workspaces[0] ?? null;
  }, [isAuthenticated, selectedWorkspaceId, workspaces]);

  const currentWorkspaceId = currentWorkspace?.workspace.id ?? null;

  // Persist the resolved selection so a missing or stale stored id (e.g. a
  // workspace the user was removed from, or a brand-new user who just landed in
  // their auto-provisioned personal workspace) converges to a real id instead
  // of leaving the dashboard wedged on `null` (finding RF-001).
  useEffect(() => {
    if (currentWorkspaceId && currentWorkspaceId !== getStoredWorkspaceId()) {
      setStoredWorkspaceId(currentWorkspaceId);
    }
  }, [currentWorkspaceId]);

  const setCurrentWorkspace = useCallback(
    (workspaceId: string) => {
      setSelectedWorkspaceId(workspaceId);
      setStoredWorkspaceId(workspaceId);
      // Clear all cached queries when switching workspaces to ensure fresh data
      // Using clear() instead of invalidateQueries() to remove stale workspace data
      queryClient.clear();
    },
    [queryClient]
  );

  const value = useMemo(
    () => ({
      workspaces,
      currentWorkspace,
      currentWorkspaceId,
      isPending,
      setCurrentWorkspace,
    }),
    [workspaces, currentWorkspace, currentWorkspaceId, isPending, setCurrentWorkspace]
  );

  return <WorkspaceContext value={value}>{children}</WorkspaceContext>;
}

export function useWorkspace() {
  const context = useContext(WorkspaceContext);
  if (context === undefined) {
    throw new Error("useWorkspace must be used within a WorkspaceProvider");
  }
  return context;
}
