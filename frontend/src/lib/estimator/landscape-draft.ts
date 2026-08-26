import {
  createLandscapeDocument,
  defaultLandscapeProposal,
  normalizeLandscapeDocument,
  type LandscapeDocumentSettings,
  type LandscapeDocumentV2,
  type LightingProjectType,
} from "@/lib/estimator/landscape-document";
import type {
  DesignerShot,
  LandscapeBomLineItem,
  LandscapePreconState,
  LandscapeProcurementState,
  LandscapeProposalSettings,
  LandscapeWorkflowTab,
} from "@/lib/estimator/types";

const DATABASE_NAME = "tribunal-estimator";
const DATABASE_VERSION = 2;
const LEGACY_DRAFT_STORE = "landscape-drafts";
const PROJECT_DRAFT_STORE = "landscape-project-drafts";

export type LandscapeProposalDraft = Pick<
  LandscapeProposalSettings,
  "selectedTierKey" | "selectedCarePlanKey"
> &
  Partial<Pick<LandscapeProposalSettings, "additionalLineItems">>;
export type LandscapeDraft = LandscapeDocumentV2;

export interface LandscapeDraftState {
  activeWorkflowTab: LandscapeWorkflowTab;
  settings: LandscapeDocumentSettings;
  proposal: LandscapeProposalSettings;
  bomLineItems: LandscapeBomLineItem[];
  procurement: Record<string, LandscapeProcurementState>;
  precon: LandscapePreconState;
}

interface LegacyLandscapeDraft {
  schemaVersion: 1;
  savedAt: string;
  shots: DesignerShot[];
}

export interface PendingLandscapeProjectDraft {
  projectId: string;
  baseServerVersion: number;
  draft: LandscapeDraft;
  dirty: boolean;
  localUpdatedAt: string;
}

type BrowserLandscapeDraftInput = LandscapeDraft | LegacyLandscapeDraft | DesignerShot[];
type LoadedLandscapeDraft = LandscapeDraft & { savedAt: string };

function hasIndexedDb(): boolean {
  return typeof indexedDB !== "undefined";
}

function openDatabase(): Promise<IDBDatabase> {
  if (!hasIndexedDb()) return Promise.reject(new Error("IndexedDB is unavailable"));
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DATABASE_NAME, DATABASE_VERSION);
    request.onupgradeneeded = () => {
      const database = request.result;
      if (!database.objectStoreNames.contains(LEGACY_DRAFT_STORE)) {
        database.createObjectStore(LEGACY_DRAFT_STORE);
      }
      if (!database.objectStoreNames.contains(PROJECT_DRAFT_STORE)) {
        database.createObjectStore(PROJECT_DRAFT_STORE);
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () =>
      reject(request.error ?? new Error("Unable to open the landscape draft database"));
  });
}

function transact<T>(
  storeName: string,
  mode: IDBTransactionMode,
  run: (store: IDBObjectStore) => IDBRequest<T>,
): Promise<T> {
  return openDatabase().then(
    (database) =>
      new Promise<T>((resolve, reject) => {
        const transaction = database.transaction(storeName, mode);
        const request = run(transaction.objectStore(storeName));
        request.onsuccess = () => resolve(request.result);
        request.onerror = () =>
          reject(request.error ?? new Error("Unable to access the landscape draft"));
        transaction.oncomplete = () => database.close();
        transaction.onerror = () => database.close();
        transaction.onabort = () => database.close();
      }),
  );
}

function normalizeDraft(value: unknown): LandscapeDraft | null {
  return normalizeLandscapeDocument(value);
}

function isPendingProjectDraft(value: unknown): value is PendingLandscapeProjectDraft {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<PendingLandscapeProjectDraft>;
  return (
    typeof candidate.projectId === "string" &&
    typeof candidate.baseServerVersion === "number" &&
    candidate.baseServerVersion > 0 &&
    candidate.dirty === true &&
    typeof candidate.localUpdatedAt === "string" &&
    normalizeDraft(candidate.draft) !== null
  );
}

export function createLandscapeDraft(
  shots: DesignerShot[],
  activeShotId: string | null,
  updatedAt = new Date().toISOString(),
  proposal?: LandscapeProposalDraft,
  liveState?: LandscapeDraftState,
  projectType: LightingProjectType = "landscape",
): LandscapeDraft {
  const document = createLandscapeDocument(shots, activeShotId, updatedAt, projectType);
  const normalized = normalizeLandscapeDocument({
    ...document,
    activeWorkflowTab: liveState?.activeWorkflowTab ?? document.activeWorkflowTab,
    settings: liveState?.settings ?? document.settings,
    proposal: {
      ...defaultLandscapeProposal(),
      ...(liveState?.proposal ?? document.proposal),
      ...proposal,
    },
    bomLineItems: liveState?.bomLineItems ?? document.bomLineItems,
    procurement: liveState?.procurement ?? document.procurement,
    precon: liveState?.precon ?? document.precon,
  });
  if (!normalized) throw new Error("Cannot create an invalid landscape draft");
  return normalized;
}

export async function loadLandscapeDraft(
  workspaceId: string,
): Promise<LoadedLandscapeDraft | null> {
  if (!workspaceId || !hasIndexedDb()) return null;
  const value = await transact<unknown>(LEGACY_DRAFT_STORE, "readonly", (store) =>
    store.get(workspaceId),
  );
  const normalized = normalizeDraft(value);
  return normalized ? { ...normalized, savedAt: normalized.updatedAt } : null;
}

export async function saveLandscapeDraft(
  workspaceId: string,
  draft: BrowserLandscapeDraftInput,
): Promise<{ savedAt: string }> {
  const input = Array.isArray(draft) ? createLandscapeDraft(draft, draft[0]?.id ?? null) : draft;
  const normalized = normalizeDraft(input);
  if (!normalized) throw new Error("Cannot save an invalid landscape draft");
  if (workspaceId && hasIndexedDb()) {
    await transact<IDBValidKey>(LEGACY_DRAFT_STORE, "readwrite", (store) =>
      store.put(normalized, workspaceId),
    );
  }
  return { savedAt: normalized.updatedAt };
}

export async function deleteLandscapeDraft(workspaceId: string): Promise<void> {
  if (!workspaceId || !hasIndexedDb()) return;
  await transact<undefined>(LEGACY_DRAFT_STORE, "readwrite", (store) => store.delete(workspaceId));
}

export async function loadPendingLandscapeDraft(
  projectId: string,
): Promise<PendingLandscapeProjectDraft | null> {
  if (!projectId || !hasIndexedDb()) return null;
  const value = await transact<unknown>(PROJECT_DRAFT_STORE, "readonly", (store) =>
    store.get(projectId),
  );
  if (!isPendingProjectDraft(value)) return null;
  const draft = normalizeDraft(value.draft);
  return draft ? { ...value, draft } : null;
}

export async function savePendingLandscapeDraft(
  record: PendingLandscapeProjectDraft,
): Promise<void> {
  if (!record.projectId || !hasIndexedDb()) return;
  const draft = normalizeDraft(record.draft);
  if (!draft || record.baseServerVersion < 1) {
    throw new Error("Cannot save an invalid pending landscape draft");
  }
  await transact<IDBValidKey>(PROJECT_DRAFT_STORE, "readwrite", (store) =>
    store.put({ ...record, draft, dirty: true }, record.projectId),
  );
}

export async function deletePendingLandscapeDraft(projectId: string): Promise<void> {
  if (!projectId || !hasIndexedDb()) return;
  await transact<undefined>(PROJECT_DRAFT_STORE, "readwrite", (store) => store.delete(projectId));
}
