"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  useCallback,
  useContext,
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

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const { isAuthenticated } = useAuth();
  const queryClient = useQueryClient();
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState<string | null>(() =>
    getStoredWorkspaceId()
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
      ? workspaces.find((w) => w.workspace.id === selectedWorkspaceId)
      : null;

    return selectedWorkspace ?? workspaces.find((w) => w.is_default) ?? workspaces[0] ?? null;
  }, [isAuthenticated, selectedWorkspaceId, workspaces]);

  const currentWorkspaceId = currentWorkspace?.workspace.id ?? null;

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
