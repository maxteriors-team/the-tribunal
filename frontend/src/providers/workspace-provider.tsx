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

/**
 * A workspace the user *deliberately* switched to in this browser.
 *
 * Deliberately a new key rather than the legacy `current_workspace_id`. That one
 * was rewritten by an effect on every resolution, so it recorded wherever the
 * user happened to *land* — not anywhere they chose — and then outranked the
 * server on the next load. An invited teammate whose default was corrected
 * server-side kept reopening the stale workspace her browser had memorised,
 * which looked exactly like the invitation never working. Treating those legacy
 * values as non-choices is the point: they are ignored, and the server's default
 * decides until the user actually picks something.
 */
const WORKSPACE_CHOICE_KEY = "current_workspace_choice";

interface WorkspaceContextType {
  workspaces: WorkspaceWithMembership[];
  currentWorkspace: WorkspaceWithMembership | null;
  currentWorkspaceId: string | null;
  isPending: boolean;
  setCurrentWorkspace: (workspaceId: string) => void;
}

const WorkspaceContext = createContext<WorkspaceContextType | undefined>(undefined);

function getStoredChoice(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return localStorage.getItem(WORKSPACE_CHOICE_KEY);
  } catch {
    return null;
  }
}

function setStoredChoice(workspaceId: string): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(WORKSPACE_CHOICE_KEY, workspaceId);
  } catch (error) {
    if (process.env.NODE_ENV !== "production") {
      console.error("Failed to save workspace choice:", error);
    }
  }
}

function clearStoredChoice(): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.removeItem(WORKSPACE_CHOICE_KEY);
  } catch {
    // Nothing to do — a stale choice is corrected on the next resolution.
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
  // accept redirect. Both sources are deliberate acts — a switcher click or an
  // explicit hand-off link — which is what earns them priority over the server's
  // default below.
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState<string | null>(
    () => getRequestedWorkspaceParam() ?? getStoredChoice()
  );

  const { data: workspaces = [], isPending } = useQuery({
    queryKey: queryKeys.workspaces.all(),
    queryFn: workspacesApi.list,
    enabled: isAuthenticated,
    ...STATIC,
  });

  const currentWorkspace = useMemo(() => {
    if (!isAuthenticated || workspaces.length === 0) return null;

    // Resolution order: what the user deliberately picked (switcher click or an
    // explicit `?workspace=` hand-off), then the server's default, then anything.
    // The server default has to outrank a merely *remembered* workspace, or a
    // default corrected server-side can never reach a browser that has already
    // memorised somewhere else.
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

  // Reconcile the remembered choice against what the server says the user can
  // actually reach.
  useEffect(() => {
    if (workspaces.length === 0) return;

    const resolve = (value: string) =>
      workspaces.find((w) => w.workspace.id === value || w.workspace.slug === value);

    // An explicit `?workspace=` hand-off — how accepting an invitation lands — is
    // as deliberate as a switcher click, so remember it. Otherwise the next plain
    // visit would quietly revert to the server default and the join would look
    // like it had come undone.
    const param = getRequestedWorkspaceParam();
    const handedOff = param ? resolve(param) : undefined;
    if (handedOff) {
      setStoredChoice(handedOff.workspace.id);
      return;
    }

    // Drop a choice that no longer resolves — the user was removed from that
    // workspace, or it was deleted. Leaving it behind would shadow the server's
    // default forever, for a workspace they cannot even open.
    const choice = getStoredChoice();
    if (choice && !resolve(choice)) {
      clearStoredChoice();
    }
  }, [workspaces]);

  const setCurrentWorkspace = useCallback(
    (workspaceId: string) => {
      setSelectedWorkspaceId(workspaceId);
      setStoredChoice(workspaceId);
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
