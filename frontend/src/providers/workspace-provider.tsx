"use client";

import * as React from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { workspacesApi, type WorkspaceWithMembership } from "@/lib/api/workspaces";
import { queryKeys } from "@/lib/query-keys";
import { useAuth } from "./auth-provider";

const WORKSPACE_STORAGE_KEY = "current_workspace_id";

interface WorkspaceContextType {
  workspaces: WorkspaceWithMembership[];
  currentWorkspace: WorkspaceWithMembership | null;
  currentWorkspaceId: string | null;
  isPending: boolean;
  setCurrentWorkspace: (workspaceId: string) => void;
}

const WorkspaceContext = React.createContext<WorkspaceContextType | undefined>(undefined);

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

export function WorkspaceProvider({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, user } = useAuth();
  const queryClient = useQueryClient();
  const [currentWorkspaceId, setCurrentWorkspaceId] = React.useState<string | null>(null);

  const { data: workspaces = [], isPending } = useQuery({
    queryKey: queryKeys.workspaces.all(),
    queryFn: workspacesApi.list,
    enabled: isAuthenticated,
    staleTime: 5 * 60 * 1000,
  });

  // Initialize current workspace from storage or default
  React.useEffect(() => {
    if (!isAuthenticated || workspaces.length === 0) return;

    const storedId = getStoredWorkspaceId();
    const storedWorkspace = workspaces.find((w) => w.workspace.id === storedId);

    if (storedWorkspace) {
      setCurrentWorkspaceId(storedId);
    } else {
      // Fall back to default workspace or first workspace
      const defaultWorkspace = workspaces.find((w) => w.is_default) || workspaces[0];
      if (defaultWorkspace) {
        setCurrentWorkspaceId(defaultWorkspace.workspace.id);
        setStoredWorkspaceId(defaultWorkspace.workspace.id);
      }
    }
  }, [isAuthenticated, workspaces, user?.default_workspace_id]);

  const currentWorkspace = React.useMemo(() => {
    if (!currentWorkspaceId) return null;
    return workspaces.find((w) => w.workspace.id === currentWorkspaceId) || null;
  }, [workspaces, currentWorkspaceId]);

  const setCurrentWorkspace = React.useCallback(
    (workspaceId: string) => {
      setCurrentWorkspaceId(workspaceId);
      setStoredWorkspaceId(workspaceId);
      // Clear all cached queries when switching workspaces to ensure fresh data
      // Using clear() instead of invalidateQueries() to remove stale workspace data
      queryClient.clear();
    },
    [queryClient]
  );

  const value = React.useMemo(
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
  const context = React.useContext(WorkspaceContext);
  if (context === undefined) {
    throw new Error("useWorkspace must be used within a WorkspaceProvider");
  }
  return context;
}
