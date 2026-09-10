import { apiGet, apiPost, apiPut, apiDelete } from "@/lib/api";
import type {
  CreatePersonaRequest,
  CreateRehearsalRequest,
  ProspectPersona,
  RehearsalRun,
  RehearsalRunSummary,
} from "@/types/roleplay";

const base = (workspaceId: string) => `/api/v1/workspaces/${workspaceId}/roleplay`;

export function isRehearsalExecuting(run: RehearsalRunSummary): boolean {
  return run.status === "pending" || (run.status === "running" && !!run.pending_action);
}

// Keep only unresolved creation identities (never dialogue or provider credentials).
// A lost HTTP response/reload must retry the same key, not start another paid run.
const pendingCreates = new Map<string, { fingerprint: string; key: string }>();

async function createRun(workspaceId: string, data: CreateRehearsalRequest): Promise<RehearsalRun> {
  const storageKey = `roleplay:pending-create:${workspaceId}`;
  const fingerprint = JSON.stringify([
    data.agent_id,
    data.persona_id,
    data.rehearsee ?? "ai",
    data.channel ?? null,
    data.max_turns ?? 6,
  ]);
  let pending = pendingCreates.get(workspaceId);
  try {
    const stored: unknown = JSON.parse(sessionStorage.getItem(storageKey) ?? "null");
    if (
      stored &&
      typeof stored === "object" &&
      "fingerprint" in stored &&
      "key" in stored &&
      typeof stored.fingerprint === "string" &&
      typeof stored.key === "string"
    ) {
      pending = { fingerprint: stored.fingerprint, key: stored.key };
    }
  } catch {
    /* Storage may be unavailable; the in-memory identity still survives HTTP retries. */
  }
  const key =
    data.idempotency_key ??
    (pending?.fingerprint === fingerprint ? pending.key : crypto.randomUUID());
  pendingCreates.set(workspaceId, { fingerprint, key });
  try {
    sessionStorage.setItem(storageKey, JSON.stringify({ fingerprint, key }));
  } catch {
    /* Private browsing can deny storage. */
  }
  const run = await apiPost<RehearsalRun>(`${base(workspaceId)}/runs`, {
    ...data,
    idempotency_key: key,
  });
  if (pendingCreates.get(workspaceId)?.key === key) {
    pendingCreates.delete(workspaceId);
    try {
      sessionStorage.removeItem(storageKey);
    } catch {
      /* Storage unavailable. */
    }
  }
  return run;
}

export const roleplayApi = {
  // === Personas ===
  listPersonas: (workspaceId: string): Promise<ProspectPersona[]> =>
    apiGet<ProspectPersona[]>(`${base(workspaceId)}/personas`),

  getPersona: (workspaceId: string, personaId: string): Promise<ProspectPersona> =>
    apiGet<ProspectPersona>(`${base(workspaceId)}/personas/${personaId}`),

  createPersona: (workspaceId: string, data: CreatePersonaRequest): Promise<ProspectPersona> =>
    apiPost<ProspectPersona>(`${base(workspaceId)}/personas`, data),

  updatePersona: (
    workspaceId: string,
    personaId: string,
    data: Partial<CreatePersonaRequest>,
  ): Promise<ProspectPersona> =>
    apiPut<ProspectPersona>(`${base(workspaceId)}/personas/${personaId}`, data),

  deletePersona: (workspaceId: string, personaId: string): Promise<void> =>
    apiDelete(`${base(workspaceId)}/personas/${personaId}`),

  // === Rehearsal runs ===
  listRuns: (
    workspaceId: string,
    params?: { agent_id?: string; limit?: number },
  ): Promise<RehearsalRunSummary[]> =>
    apiGet<RehearsalRunSummary[]>(`${base(workspaceId)}/runs`, { params }),

  getRun: (workspaceId: string, runId: string): Promise<RehearsalRun> =>
    apiGet<RehearsalRun>(`${base(workspaceId)}/runs/${runId}`),

  createRun,

  advanceTurn: (
    workspaceId: string,
    runId: string,
    message: string,
    expectedTurnCount: number,
  ): Promise<RehearsalRun> =>
    apiPost<RehearsalRun>(`${base(workspaceId)}/runs/${runId}/turn`, {
      message,
      expected_turn_count: expectedTurnCount,
    }),

  scoreRun: (workspaceId: string, runId: string): Promise<RehearsalRun> =>
    apiPost<RehearsalRun>(`${base(workspaceId)}/runs/${runId}/score`),

  retryRun: (
    workspaceId: string,
    runId: string,
    expectedAttemptCount: number,
  ): Promise<RehearsalRun> =>
    apiPost<RehearsalRun>(`${base(workspaceId)}/runs/${runId}/retry`, {
      expected_attempt_count: expectedAttemptCount,
    }),

  deleteRun: (workspaceId: string, runId: string): Promise<void> =>
    apiDelete(`${base(workspaceId)}/runs/${runId}`),
};
