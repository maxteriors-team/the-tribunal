"use client";

import { useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  lightingProjectsApi,
  type LandscapeDraftDocument,
  type LightingProjectDetail,
} from "@/lib/api/lighting-projects";
import { normalizeLandscapeDocument as normalizeDomainDocument } from "@/lib/estimator/landscape-document";
import {
  deletePendingLandscapeDraft,
  loadPendingLandscapeDraft,
  savePendingLandscapeDraft,
  type LandscapeDraft,
  type PendingLandscapeProjectDraft,
} from "@/lib/estimator/landscape-draft";
import { queryKeys } from "@/lib/query-keys";

const SERVER_DEBOUNCE_MS = 800;
const RETRY_DELAYS_MS = [2_000, 5_000, 15_000, 30_000] as const;

export type LightingProjectSaveStatus =
  | "loading"
  | "saved"
  | "pending"
  | "saving"
  | "error"
  | "conflict";

export const LIGHTING_PROJECT_SAVE_LABELS: Record<LightingProjectSaveStatus, string> = {
  loading: "Checking this device...",
  saved: "Saved to Tribunal",
  pending: "Saved on this device; sync pending",
  saving: "Syncing to Tribunal...",
  error: "Saved on this device; sync pending",
  conflict: "Save conflict needs review",
};

export interface LightingProjectConflict {
  localDraft: LandscapeDraft;
  currentVersion: number;
  updaterName: string | null;
  updatedAt: string;
  source: "server" | "stale-device-draft";
}

interface UseLightingProjectAutosaveOptions {
  workspaceId: string;
  project: LightingProjectDetail;
  onCopyCreated: (project: LightingProjectDetail) => void;
}

interface UseLightingProjectAutosaveResult {
  project: LightingProjectDetail;
  initialDraft: LandscapeDraft;
  resetKey: number;
  isReady: boolean;
  status: LightingProjectSaveStatus;
  statusLabel: string;
  errorMessage: string | null;
  conflict: LightingProjectConflict | null;
  onDraftChange: (draft: LandscapeDraft, options?: { immediate?: boolean }) => void;
  retry: () => void;
  /** Resolves only after all browser/server writes settle; rejects on conflict/error. */
  saveNow: () => Promise<LightingProjectDetail>;
  loadTribunalVersion: () => Promise<void>;
  saveWorkAsCopy: () => Promise<void>;
  updateProjectName: (name: string) => Promise<void>;
}

interface ConflictResponseDetails {
  current_version?: unknown;
  updater_name?: unknown;
  updated_at?: unknown;
}

export function normalizeLandscapeDocument(document: LandscapeDraftDocument): LandscapeDraft {
  const normalized = normalizeDomainDocument(document);
  if (!normalized) {
    throw new Error("Tribunal returned an invalid landscape project document");
  }
  return normalized;
}

function conflictDetails(error: unknown): ConflictResponseDetails | null {
  if (!isAxiosError(error) || error.response?.status !== 409) return null;
  const body = error.response.data as
    | {
        details?: ConflictResponseDetails;
        error?: { details?: ConflictResponseDetails };
      }
    | undefined;
  return body?.details ?? body?.error?.details ?? {};
}

function retryableRequestError(error: unknown): boolean {
  if (!isAxiosError(error)) return true;
  return error.response === undefined || error.response.status >= 500;
}

function requestErrorMessage(error: unknown): string {
  if (!isAxiosError(error)) return "Tribunal could not sync this draft.";
  const body = error.response?.data as
    | { detail?: unknown; message?: unknown; error?: { message?: unknown } }
    | undefined;
  const detail = body?.message ?? body?.error?.message ?? body?.detail;
  return typeof detail === "string" ? detail : "Tribunal could not sync this draft.";
}

export function useLightingProjectAutosave({
  workspaceId,
  project: loadedProject,
  onCopyCreated,
}: UseLightingProjectAutosaveOptions): UseLightingProjectAutosaveResult {
  const queryClient = useQueryClient();
  const loadedProjectRef = useRef(loadedProject);

  const serverDraft = normalizeLandscapeDocument(loadedProject.document);
  const [project, setProject] = useState(loadedProject);
  const [initialDraft, setInitialDraft] = useState(serverDraft);
  const [resetKey, setResetKey] = useState(0);
  const [isReady, setIsReady] = useState(false);
  const [status, setStatus] = useState<LightingProjectSaveStatus>("loading");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [conflict, setConflict] = useState<LightingProjectConflict | null>(null);

  const mountedRef = useRef(true);
  const projectRef = useRef(loadedProject);
  const serverVersionRef = useRef(loadedProject.version);
  const latestDraftRef = useRef(serverDraft);
  const queuedDraftRef = useRef<LandscapeDraft | null>(null);
  const inFlightRef = useRef(false);
  const draftSyncFailedRef = useRef(false);
  const conflictRef = useRef<LightingProjectConflict | null>(null);
  const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const retryAttemptRef = useRef(0);
  const storageChainRef = useRef<Promise<void>>(Promise.resolve());
  const flushRef = useRef<() => Promise<void>>(async () => {});

  const setCurrentProject = useCallback(
    (nextProject: LightingProjectDetail) => {
      projectRef.current = nextProject;
      serverVersionRef.current = nextProject.version;
      if (mountedRef.current) setProject(nextProject);
      queryClient.setQueryData(
        queryKeys.lightingProjects.detail(workspaceId, nextProject.id),
        nextProject,
      );
      void queryClient.invalidateQueries({
        queryKey: queryKeys.lightingProjects.all(workspaceId),
        refetchType: "inactive",
      });
    },
    [queryClient, workspaceId],
  );

  const runStorageOperation = useCallback((operation: () => Promise<void>) => {
    storageChainRef.current = storageChainRef.current
      .then(operation, operation)
      .catch((error: unknown) => {
        if (!mountedRef.current) return;
        setErrorMessage(
          error instanceof Error
            ? `Browser backup unavailable: ${error.message}`
            : "Browser backup is unavailable for this draft.",
        );
        setStatus("error");
      });
    return storageChainRef.current;
  }, []);

  const persistPendingDraft = useCallback(
    (draft: LandscapeDraft, baseServerVersion: number) =>
      runStorageOperation(() =>
        savePendingLandscapeDraft({
          projectId: loadedProject.id,
          baseServerVersion,
          draft,
          dirty: true,
          localUpdatedAt: new Date().toISOString(),
        }),
      ),
    [loadedProject.id, runStorageOperation],
  );

  const clearPendingDraft = useCallback(
    () => runStorageOperation(() => deletePendingLandscapeDraft(loadedProject.id)),
    [loadedProject.id, runStorageOperation],
  );

  const clearDebounceTimer = useCallback(() => {
    if (debounceTimerRef.current !== null) {
      clearTimeout(debounceTimerRef.current);
      debounceTimerRef.current = null;
    }
  }, []);

  const clearRetryTimer = useCallback(() => {
    if (retryTimerRef.current !== null) {
      clearTimeout(retryTimerRef.current);
      retryTimerRef.current = null;
    }
  }, []);

  const scheduleFlush = useCallback(
    (delay = SERVER_DEBOUNCE_MS) => {
      clearDebounceTimer();
      if (conflictRef.current || inFlightRef.current) return;
      debounceTimerRef.current = setTimeout(() => {
        debounceTimerRef.current = null;
        void flushRef.current();
      }, delay);
    },
    [clearDebounceTimer],
  );

  const scheduleAutomaticRetry = useCallback(() => {
    clearRetryTimer();
    if (typeof navigator !== "undefined" && !navigator.onLine) return;
    const delay = RETRY_DELAYS_MS[Math.min(retryAttemptRef.current, RETRY_DELAYS_MS.length - 1)];
    retryAttemptRef.current += 1;
    retryTimerRef.current = setTimeout(() => {
      retryTimerRef.current = null;
      void flushRef.current();
    }, delay);
  }, [clearRetryTimer]);

  const openConflict = useCallback(
    (nextConflict: LightingProjectConflict) => {
      conflictRef.current = nextConflict;
      draftSyncFailedRef.current = true;
      clearDebounceTimer();
      clearRetryTimer();
      if (!mountedRef.current) return;
      setConflict(nextConflict);
      setStatus("conflict");
      setErrorMessage(null);
    },
    [clearDebounceTimer, clearRetryTimer],
  );

  const flushDraft = useCallback(async () => {
    if (inFlightRef.current || conflictRef.current || queuedDraftRef.current === null) {
      return;
    }

    await storageChainRef.current;
    const draft = queuedDraftRef.current;
    if (!draft || conflictRef.current) return;
    queuedDraftRef.current = null;
    inFlightRef.current = true;
    draftSyncFailedRef.current = false;
    const expectedVersion = serverVersionRef.current;
    if (mountedRef.current) {
      setStatus("saving");
      setErrorMessage(null);
    }

    let continueWithQueuedDraft = false;
    try {
      const updatedProject = await lightingProjectsApi.update(workspaceId, loadedProject.id, {
        expected_version: expectedVersion,
        document: draft,
      });
      retryAttemptRef.current = 0;
      draftSyncFailedRef.current = false;
      setCurrentProject(updatedProject);

      if (queuedDraftRef.current) {
        await persistPendingDraft(queuedDraftRef.current, updatedProject.version);
        continueWithQueuedDraft = true;
        if (mountedRef.current) setStatus("pending");
      } else {
        await clearPendingDraft();
        if (queuedDraftRef.current) {
          await persistPendingDraft(queuedDraftRef.current, updatedProject.version);
          continueWithQueuedDraft = true;
          if (mountedRef.current) setStatus("pending");
        } else if (mountedRef.current) {
          setStatus("saved");
        }
      }
    } catch (error: unknown) {
      const localDraft = queuedDraftRef.current ?? draft;
      queuedDraftRef.current = localDraft;
      await persistPendingDraft(localDraft, expectedVersion);
      const details = conflictDetails(error);
      if (details) {
        openConflict({
          localDraft,
          currentVersion:
            typeof details.current_version === "number"
              ? details.current_version
              : expectedVersion + 1,
          updaterName: typeof details.updater_name === "string" ? details.updater_name : null,
          updatedAt:
            typeof details.updated_at === "string" ? details.updated_at : new Date().toISOString(),
          source: "server",
        });
      } else {
        draftSyncFailedRef.current = true;
        if (mountedRef.current) {
          setStatus("error");
          setErrorMessage(requestErrorMessage(error));
        }
        if (retryableRequestError(error)) scheduleAutomaticRetry();
      }
    } finally {
      inFlightRef.current = false;
      if (continueWithQueuedDraft && !conflictRef.current) scheduleFlush(0);
    }
  }, [
    clearPendingDraft,
    loadedProject.id,
    openConflict,
    persistPendingDraft,
    scheduleAutomaticRetry,
    scheduleFlush,
    setCurrentProject,
    workspaceId,
  ]);

  useEffect(() => {
    flushRef.current = flushDraft;
  }, [flushDraft]);

  useEffect(() => {
    loadedProjectRef.current = loadedProject;
  }, [loadedProject]);

  const onDraftChange = useCallback(
    (draft: LandscapeDraft, options?: { immediate?: boolean }) => {
      if (conflictRef.current) return;
      latestDraftRef.current = draft;
      queuedDraftRef.current = draft;
      if (mountedRef.current) {
        setStatus("pending");
        setErrorMessage(null);
      }
      void persistPendingDraft(draft, serverVersionRef.current);
      if (!inFlightRef.current) scheduleFlush(options?.immediate ? 0 : undefined);
    },
    [persistPendingDraft, scheduleFlush],
  );

  const retry = useCallback(() => {
    if (conflictRef.current || queuedDraftRef.current === null) return;
    retryAttemptRef.current = 0;
    clearRetryTimer();
    if (mountedRef.current) {
      setStatus("pending");
      setErrorMessage(null);
    }
    scheduleFlush(0);
  }, [clearRetryTimer, scheduleFlush]);

  const saveNow = useCallback(async (): Promise<LightingProjectDetail> => {
    clearDebounceTimer();
    const deadline = Date.now() + 30_000;
    while (inFlightRef.current || queuedDraftRef.current) {
      if (conflictRef.current) {
        throw new Error("Resolve the drawing conflict before creating the proposal.");
      }
      if (draftSyncFailedRef.current) {
        throw new Error("Retry the pending drawing sync before creating the proposal.");
      }
      await flushRef.current();
      if (Date.now() >= deadline) {
        throw new Error("The drawing is still syncing. Retry the proposal in a moment.");
      }
      if (inFlightRef.current || queuedDraftRef.current) {
        await new Promise((resolve) => setTimeout(resolve, 20));
      }
    }
    await storageChainRef.current;
    if (conflictRef.current || draftSyncFailedRef.current) {
      throw new Error("The drawing must finish syncing before creating the proposal.");
    }
    return projectRef.current;
  }, [clearDebounceTimer]);

  const loadTribunalVersion = useCallback(async () => {
    if (!conflictRef.current) return;
    if (mountedRef.current) setErrorMessage(null);
    try {
      const currentProject = await lightingProjectsApi.get(workspaceId, loadedProject.id);
      await clearPendingDraft();
      queuedDraftRef.current = null;
      const draft = normalizeLandscapeDocument(currentProject.document);
      latestDraftRef.current = draft;
      conflictRef.current = null;
      draftSyncFailedRef.current = false;
      setCurrentProject(currentProject);
      if (mountedRef.current) {
        setInitialDraft(draft);
        setResetKey((key) => key + 1);
        setConflict(null);
        setStatus("saved");
      }
    } catch (error: unknown) {
      if (mountedRef.current) setErrorMessage(requestErrorMessage(error));
      throw error;
    }
  }, [clearPendingDraft, loadedProject.id, setCurrentProject, workspaceId]);

  const saveWorkAsCopy = useCallback(async () => {
    const activeConflict = conflictRef.current;
    if (!activeConflict) return;
    if (mountedRef.current) setErrorMessage(null);
    try {
      const sourceProject = projectRef.current;
      const copy = await lightingProjectsApi.create(workspaceId, {
        contact_id: sourceProject.contact_id,
        service_location_id: sourceProject.service_location_id,
        opportunity_id: sourceProject.opportunity_id,
        assigned_user_id: sourceProject.assigned_user_id,
        name: `${sourceProject.name} copy`,
        document: activeConflict.localDraft,
      });
      await clearPendingDraft();
      queuedDraftRef.current = null;
      conflictRef.current = null;
      draftSyncFailedRef.current = false;
      if (mountedRef.current) {
        setConflict(null);
        setStatus("saved");
      }
      void queryClient.invalidateQueries({
        queryKey: queryKeys.lightingProjects.all(workspaceId),
      });
      onCopyCreated(copy);
    } catch (error: unknown) {
      if (mountedRef.current) setErrorMessage(requestErrorMessage(error));
      throw error;
    }
  }, [clearPendingDraft, onCopyCreated, queryClient, workspaceId]);

  const updateProjectName = useCallback(
    async (name: string) => {
      const normalizedName = name.trim();
      if (!normalizedName || normalizedName === projectRef.current.name) return;
      clearDebounceTimer();
      await flushRef.current();
      const waitDeadline = Date.now() + 30_000;
      while (inFlightRef.current || queuedDraftRef.current) {
        if (conflictRef.current) {
          throw new Error("Resolve the drawing conflict before renaming this project.");
        }
        if (draftSyncFailedRef.current) {
          throw new Error("Retry the pending drawing sync before renaming this project.");
        }
        if (Date.now() >= waitDeadline) {
          throw new Error("The drawing is still syncing. Retry the project name in a moment.");
        }
        await new Promise((resolve) => setTimeout(resolve, 20));
        await flushRef.current();
      }

      inFlightRef.current = true;
      if (mountedRef.current) setStatus("saving");
      try {
        const updatedProject = await lightingProjectsApi.update(workspaceId, loadedProject.id, {
          expected_version: serverVersionRef.current,
          name: normalizedName,
        });
        setCurrentProject(updatedProject);
        if (mountedRef.current) setStatus("saved");
      } catch (error: unknown) {
        const details = conflictDetails(error);
        if (details) {
          openConflict({
            localDraft: latestDraftRef.current,
            currentVersion:
              typeof details.current_version === "number"
                ? details.current_version
                : serverVersionRef.current + 1,
            updaterName: typeof details.updater_name === "string" ? details.updater_name : null,
            updatedAt:
              typeof details.updated_at === "string"
                ? details.updated_at
                : new Date().toISOString(),
            source: "server",
          });
        } else if (mountedRef.current) {
          setStatus("error");
          setErrorMessage(requestErrorMessage(error));
        }
        throw error;
      } finally {
        inFlightRef.current = false;
        if (queuedDraftRef.current && !conflictRef.current) scheduleFlush(0);
      }
    },
    [
      clearDebounceTimer,
      loadedProject.id,
      openConflict,
      scheduleFlush,
      setCurrentProject,
      workspaceId,
    ],
  );

  useEffect(() => {
    mountedRef.current = true;
    let cancelled = false;
    const currentLoadedProject = loadedProjectRef.current;
    const currentServerDraft = normalizeLandscapeDocument(currentLoadedProject.document);
    projectRef.current = currentLoadedProject;
    serverVersionRef.current = currentLoadedProject.version;
    latestDraftRef.current = currentServerDraft;
    setProject(currentLoadedProject);
    setInitialDraft(currentServerDraft);
    setStatus("loading");
    setErrorMessage(null);
    setConflict(null);
    conflictRef.current = null;
    draftSyncFailedRef.current = false;
    queuedDraftRef.current = null;
    setIsReady(false);

    void loadPendingLandscapeDraft(currentLoadedProject.id)
      .then((pendingRecord: PendingLandscapeProjectDraft | null) => {
        if (cancelled) return;
        if (!pendingRecord?.dirty) {
          setStatus("saved");
          setIsReady(true);
          return;
        }

        if (pendingRecord.baseServerVersion === currentLoadedProject.version) {
          latestDraftRef.current = pendingRecord.draft;
          queuedDraftRef.current = pendingRecord.draft;
          setInitialDraft(pendingRecord.draft);
          setStatus("pending");
          setIsReady(true);
          scheduleFlush();
          return;
        }

        const staleConflict: LightingProjectConflict = {
          localDraft: pendingRecord.draft,
          currentVersion: currentLoadedProject.version,
          updaterName: currentLoadedProject.updater_name ?? null,
          updatedAt: currentLoadedProject.updated_at,
          source: "stale-device-draft",
        };
        setIsReady(true);
        openConflict(staleConflict);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setStatus("error");
        setErrorMessage(
          error instanceof Error
            ? `Browser recovery unavailable: ${error.message}`
            : "Browser recovery is unavailable.",
        );
        setIsReady(true);
      });

    return () => {
      cancelled = true;
      mountedRef.current = false;
      clearDebounceTimer();
      clearRetryTimer();
    };
  }, [clearDebounceTimer, clearRetryTimer, loadedProject.id, openConflict, scheduleFlush]);

  useEffect(() => {
    const handleOnline = () => {
      if (!conflictRef.current && queuedDraftRef.current && !inFlightRef.current) {
        retry();
      }
    };
    window.addEventListener("online", handleOnline);
    return () => window.removeEventListener("online", handleOnline);
  }, [retry]);

  useEffect(() => {
    if (
      loadedProject.version <= serverVersionRef.current ||
      inFlightRef.current ||
      queuedDraftRef.current ||
      conflictRef.current
    ) {
      return;
    }
    const nextDraft = normalizeLandscapeDocument(loadedProject.document);
    latestDraftRef.current = nextDraft;
    setCurrentProject(loadedProject);
    setInitialDraft(nextDraft);
    setResetKey((key) => key + 1);
  }, [loadedProject, setCurrentProject]);

  return {
    project,
    initialDraft,
    resetKey,
    isReady,
    status,
    statusLabel: LIGHTING_PROJECT_SAVE_LABELS[status],
    errorMessage,
    conflict,
    onDraftChange,
    retry,
    saveNow,
    loadTribunalVersion,
    saveWorkAsCopy,
    updateProjectName,
  };
}
