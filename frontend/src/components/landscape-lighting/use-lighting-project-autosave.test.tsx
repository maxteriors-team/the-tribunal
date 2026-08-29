import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { LightingProjectDetail } from "@/lib/api/lighting-projects";
import type { LandscapeDraft, PendingLandscapeProjectDraft } from "@/lib/estimator/landscape-draft";

import { useLightingProjectAutosave } from "./use-lighting-project-autosave";

const apiMocks = vi.hoisted(() => ({
  create: vi.fn(),
  get: vi.fn(),
  update: vi.fn(),
}));

const draftStorageMocks = vi.hoisted(() => ({
  deletePending: vi.fn(),
  loadPending: vi.fn(),
  savePending: vi.fn(),
}));

vi.mock("@/lib/api/lighting-projects", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api/lighting-projects")>();
  return {
    ...original,
    lightingProjectsApi: apiMocks,
  };
});

vi.mock("@/lib/estimator/landscape-draft", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/estimator/landscape-draft")>();
  return {
    ...original,
    deletePendingLandscapeDraft: draftStorageMocks.deletePending,
    loadPendingLandscapeDraft: draftStorageMocks.loadPending,
    savePendingLandscapeDraft: draftStorageMocks.savePending,
  };
});

const WORKSPACE_ID = "c08cc985-944f-48f8-987c-7fc171afdfe2";
const PROJECT_ID = "e83683ac-426a-4a18-b9ad-dffb76574d69";

function makeDraft(
  id = "shot-1",
  projectType: LandscapeDraft["projectType"] = "landscape",
): LandscapeDraft {
  return {
    version: 2,
    projectType,
    activeShotId: id,
    shots: [
      {
        id,
        photo: {
          dataUrl: "data:image/png;base64,AAAA",
          width: 1200,
          height: 800,
        },
        design: { calibration: null, runs: [], items: [] },
        dusk: 0.4,
      },
    ],
    updatedAt: "2026-08-11T10:00:00.000Z",
  };
}

function makeProject(version = 1, draft: LandscapeDraft = makeDraft()): LightingProjectDetail {
  return {
    id: PROJECT_ID,
    workspace_id: WORKSPACE_ID,
    contact_id: 42,
    contact_name: "Pat Lee",
    service_location_id: null,
    opportunity_id: null,
    assigned_user_id: null,
    name: "Patio lighting",
    project_type: draft.projectType,
    status: "active",
    version,
    installation_shot_id: null,
    updated_by_id: 7,
    updater_name: "Morgan Manager",
    created_at: "2026-08-11T09:00:00.000Z",
    updated_at: `2026-08-11T10:0${version}:00.000Z`,
    created_by_id: 7,
    document: draft,
  };
}

function makeWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: queryClient }, children);
  return { wrapper, queryClient };
}

async function renderAutosave(project = makeProject(), onCopyCreated = vi.fn()) {
  const { wrapper } = makeWrapper();
  const hook = renderHook(
    () =>
      useLightingProjectAutosave({
        workspaceId: WORKSPACE_ID,
        project,
        onCopyCreated,
      }),
    { wrapper },
  );
  await waitFor(() => expect(hook.result.current.isReady).toBe(true));
  return { ...hook, onCopyCreated };
}

beforeEach(() => {
  draftStorageMocks.loadPending.mockResolvedValue(null);
  draftStorageMocks.savePending.mockResolvedValue(undefined);
  draftStorageMocks.deletePending.mockResolvedValue(undefined);
  apiMocks.create.mockReset();
  apiMocks.get.mockReset();
  apiMocks.update.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
  vi.clearAllMocks();
});

describe("useLightingProjectAutosave", () => {
  it("preserves wire circuit metadata and fixture assignments from the server document", async () => {
    const draft = makeDraft();
    draft.shots[0].design.runs = [
      {
        id: "circuit-1",
        productId: "landscape-wire",
        points: [
          { x: 10, y: 10 },
          { x: 100, y: 100 },
        ],
        circuitLabel: "C1",
        transformerId: "transformer-1",
        wireGauge: 10,
        sourceVoltage: 13,
      },
    ];
    draft.proposal = {
      ...(draft.proposal ?? {
        designIntent: "",
        showCombinedTotal: true,
        showFixtureDetails: true,
        zones: [],
        paymentMilestones: [],
        electricalResponsibility: "",
        enhancements: [],
        commitments: [],
        signatureName: "",
        signatureDate: null,
      }),
      selectedTierKey: "better",
      selectedCarePlanKey: "essential",
    };
    draft.shots[0].design.items = [
      {
        id: "fixture-1",
        productId: "fixture-uplight",
        at: { x: 100, y: 100 },
        sizePx: 30,
        circuitId: "circuit-1",
      },
      {
        id: "transformer-1",
        productId: "fixture-transformer",
        at: { x: 10, y: 10 },
        sizePx: 30,
      },
    ];

    const { result } = await renderAutosave(makeProject(1, draft));

    expect(result.current.initialDraft.shots[0].design.runs[0]).toMatchObject({
      circuitLabel: "C1",
      transformerId: "transformer-1",
      wireGauge: 10,
      sourceVoltage: 13,
    });
    expect(result.current.initialDraft.shots[0].design.items[0].circuitId).toBe("circuit-1");
    expect(result.current.initialDraft.proposal).toMatchObject({
      selectedTierKey: "better",
      selectedCarePlanKey: "essential",
    });
  });

  it("debounces changes, adopts the server version, and clears the local pending copy", async () => {
    const { result } = await renderAutosave();
    vi.useFakeTimers();
    const changedDraft = makeDraft("changed");
    apiMocks.update.mockResolvedValue(makeProject(2, changedDraft));

    act(() => result.current.onDraftChange(changedDraft));
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(result.current.statusLabel).toBe("Saved on this device; sync pending");
    expect(apiMocks.update).not.toHaveBeenCalled();
    expect(draftStorageMocks.savePending).toHaveBeenCalledWith(
      expect.objectContaining({
        projectId: PROJECT_ID,
        baseServerVersion: 1,
        draft: changedDraft,
        dirty: true,
      }),
    );

    await act(async () => vi.advanceTimersByTimeAsync(799));
    expect(apiMocks.update).not.toHaveBeenCalled();
    await act(async () => vi.advanceTimersByTimeAsync(1));

    await vi.waitFor(() => expect(result.current.status).toBe("saved"));
    expect(apiMocks.update).toHaveBeenCalledWith(WORKSPACE_ID, PROJECT_ID, {
      expected_version: 1,
      document: changedDraft,
    });
    expect(result.current.project.version).toBe(2);
    expect(draftStorageMocks.deletePending).toHaveBeenCalledWith(PROJECT_ID);
    expect(draftStorageMocks.deletePending).toHaveBeenCalledWith(PROJECT_ID);
  });

  it("saveNow flushes the pending design before proposal construction", async () => {
    const { result } = await renderAutosave();
    const changedDraft = makeDraft("installation-sheet");
    apiMocks.update.mockResolvedValue(makeProject(2, changedDraft));

    act(() => result.current.onDraftChange(changedDraft));
    let saved: LightingProjectDetail | undefined;
    await act(async () => {
      saved = await result.current.saveNow();
    });

    expect(apiMocks.update).toHaveBeenCalledWith(WORKSPACE_ID, PROJECT_ID, {
      expected_version: 1,
      document: changedDraft,
    });
    expect(saved?.version).toBe(2);
    expect(saved?.document.activeShotId).toBe("installation-sheet");
  });

  it("saveNow retries a failed drawing sync instead of blocking the proposal", async () => {
    const { result } = await renderAutosave();
    const changedDraft = makeDraft("retried-sync");
    apiMocks.update
      .mockRejectedValueOnce({ isAxiosError: true, message: "Network Error" })
      .mockResolvedValueOnce(makeProject(2, changedDraft));

    act(() => result.current.onDraftChange(changedDraft, { immediate: true }));
    await waitFor(() => expect(result.current.status).toBe("error"));

    let saved: LightingProjectDetail | undefined;
    await act(async () => {
      saved = await result.current.saveNow();
    });

    expect(apiMocks.update).toHaveBeenCalledTimes(2);
    expect(saved?.version).toBe(2);
    expect(saved?.document.activeShotId).toBe("retried-sync");
  });

  it("saveNow reports why the drawing sync failed when the retry fails too", async () => {
    const { result } = await renderAutosave();
    apiMocks.update.mockRejectedValue({
      isAxiosError: true,
      response: { status: 422, data: { message: "Drawing rejected by Tribunal." } },
    });

    act(() => result.current.onDraftChange(makeDraft("rejected-sync"), { immediate: true }));
    await waitFor(() => expect(result.current.status).toBe("error"));

    await act(async () => {
      await expect(result.current.saveNow()).rejects.toThrow("Drawing rejected by Tribunal.");
    });
    expect(apiMocks.update).toHaveBeenCalledTimes(2);
  });
  it("flushes a newly placed fixture without waiting for the drawing debounce", async () => {
    const { result } = await renderAutosave();
    vi.useFakeTimers();
    const changedDraft = makeDraft("fixture-placed");
    changedDraft.shots[0].design.items = [
      {
        id: "fixture-1",
        productId: "fixture-uplight",
        at: { x: 100, y: 120 },
        sizePx: 28,
        markerColor: "#F2C94C",
      },
    ];
    apiMocks.update.mockResolvedValue(makeProject(2, changedDraft));

    act(() => result.current.onDraftChange(changedDraft, { immediate: true }));
    expect(apiMocks.update).not.toHaveBeenCalled();
    await act(async () => vi.advanceTimersByTimeAsync(0));

    await vi.waitFor(() => expect(apiMocks.update).toHaveBeenCalledTimes(1));
    expect(apiMocks.update).toHaveBeenCalledWith(WORKSPACE_ID, PROJECT_ID, {
      expected_version: 1,
      document: changedDraft,
    });
  });

  it("allows one PATCH in flight and coalesces later edits into one latest PATCH", async () => {
    const { result } = await renderAutosave();
    vi.useFakeTimers();
    const firstDraft = makeDraft("first");
    const secondDraft = makeDraft("second");
    const thirdDraft = makeDraft("third");
    let resolveFirst: ((project: LightingProjectDetail) => void) | undefined;
    apiMocks.update
      .mockImplementationOnce(
        () =>
          new Promise<LightingProjectDetail>((resolve) => {
            resolveFirst = resolve;
          }),
      )
      .mockResolvedValueOnce(makeProject(3, thirdDraft));

    act(() => result.current.onDraftChange(firstDraft));
    await act(async () => vi.advanceTimersByTimeAsync(800));
    expect(apiMocks.update).toHaveBeenCalledTimes(1);

    act(() => {
      result.current.onDraftChange(secondDraft);
      result.current.onDraftChange(thirdDraft);
    });
    await act(async () => vi.advanceTimersByTimeAsync(2_000));
    expect(apiMocks.update).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolveFirst?.(makeProject(2, firstDraft));
      await Promise.resolve();
    });
    await act(async () => vi.advanceTimersByTimeAsync(0));
    await vi.waitFor(() => expect(apiMocks.update).toHaveBeenCalledTimes(2));
    expect(apiMocks.update.mock.calls[1]).toEqual([
      WORKSPACE_ID,
      PROJECT_ID,
      { expected_version: 2, document: thirdDraft },
    ]);
    await vi.waitFor(() => expect(result.current.project.version).toBe(3));
  });

  it("keeps a network failure pending and retries when the browser comes online", async () => {
    const { result } = await renderAutosave();
    vi.useFakeTimers();
    const changedDraft = makeDraft("offline");
    apiMocks.update
      .mockRejectedValueOnce({ isAxiosError: true, message: "Network Error" })
      .mockResolvedValueOnce(makeProject(2, changedDraft));

    act(() => result.current.onDraftChange(changedDraft));
    await act(async () => vi.advanceTimersByTimeAsync(800));
    await vi.waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.statusLabel).toBe("Saved on this device; sync pending");
    expect(draftStorageMocks.deletePending).not.toHaveBeenCalled();

    act(() => window.dispatchEvent(new Event("online")));
    await act(async () => vi.advanceTimersByTimeAsync(0));
    await vi.waitFor(() => expect(apiMocks.update).toHaveBeenCalledTimes(2));
    await vi.waitFor(() => expect(result.current.status).toBe("saved"));
  });

  it("does not leave project-name saving hung behind a failed drawing sync", async () => {
    const { result } = await renderAutosave();
    vi.useFakeTimers();
    apiMocks.update.mockRejectedValue({
      isAxiosError: true,
      message: "Network Error",
    });

    act(() => result.current.onDraftChange(makeDraft("pending-name")));
    await act(async () => vi.advanceTimersByTimeAsync(800));
    await vi.waitFor(() => expect(result.current.status).toBe("error"));

    await act(async () => {
      await expect(result.current.updateProjectName("Renamed while offline")).rejects.toThrow(
        "Retry the pending drawing sync",
      );
    });
  });

  it("detects a stale device draft before retrying and can load the Tribunal version", async () => {
    const staleDraft = makeDraft("stale-local");
    const pending: PendingLandscapeProjectDraft = {
      projectId: PROJECT_ID,
      baseServerVersion: 1,
      draft: staleDraft,
      dirty: true,
      localUpdatedAt: "2026-08-11T10:00:00.000Z",
    };
    draftStorageMocks.loadPending.mockResolvedValue(pending);
    const currentProject = makeProject(2, makeDraft("server"));
    apiMocks.get.mockResolvedValue(currentProject);

    const { result } = await renderAutosave(currentProject);
    expect(result.current.status).toBe("conflict");
    expect(result.current.conflict).toMatchObject({
      source: "stale-device-draft",
      localDraft: staleDraft,
      currentVersion: 2,
    });
    expect(apiMocks.update).not.toHaveBeenCalled();

    await act(async () => result.current.loadTribunalVersion());
    expect(apiMocks.get).toHaveBeenCalledWith(WORKSPACE_ID, PROJECT_ID);
    expect(draftStorageMocks.deletePending).toHaveBeenCalledWith(PROJECT_ID);
    expect(result.current.conflict).toBeNull();
    expect(result.current.initialDraft.activeShotId).toBe("server");
    expect(result.current.resetKey).toBe(1);
  });

  it("stops on HTTP 409 and preserves local work in a separately created project", async () => {
    const { result, onCopyCreated } = await renderAutosave();
    vi.useFakeTimers();
    const changedDraft = makeDraft("my-work");
    apiMocks.update.mockRejectedValue({
      isAxiosError: true,
      response: {
        status: 409,
        data: {
          code: "lighting_project_version_conflict",
          message: "Lighting project changed since this draft was loaded",
          details: {
            current_version: 4,
            updater_name: "Alex Teammate",
            updated_at: "2026-08-11T10:30:00.000Z",
          },
        },
      },
    });
    const copy = {
      ...makeProject(1, changedDraft),
      id: "cba72ecf-8f03-452c-941d-23886b928477",
      name: "Patio lighting copy",
    };
    apiMocks.create.mockResolvedValue(copy);

    act(() => result.current.onDraftChange(changedDraft));
    await act(async () => vi.advanceTimersByTimeAsync(800));
    await vi.waitFor(() => expect(result.current.status).toBe("conflict"));
    expect(result.current.conflict).toMatchObject({
      currentVersion: 4,
      updaterName: "Alex Teammate",
      localDraft: changedDraft,
    });

    await act(async () => result.current.saveWorkAsCopy());
    expect(apiMocks.create).toHaveBeenCalledWith(
      WORKSPACE_ID,
      expect.objectContaining({
        contact_id: 42,
        name: "Patio lighting copy",
        project_type: "landscape",
        document: changedDraft,
      }),
    );
    expect(onCopyCreated).toHaveBeenCalledWith(copy);
    expect(draftStorageMocks.deletePending).toHaveBeenCalledWith(PROJECT_ID);
  });
});
