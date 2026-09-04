import { apiGet } from "@/lib/api";
import type { Schemas } from "@/lib/api/_client";

/** Receptionist scorecard payload (generated from the OpenAPI schema). */
export type ReceptionistScorecard = Schemas["ReceptionistScorecard"];
export type CallReasonStat = Schemas["CallReasonStat"];

export type TechnicianActivityScorecardRow = Schemas["TechnicianActivityScorecardRow"];
export type OfficeRepScorecardRow = Schemas["OfficeRepScorecardRow"];

export interface ScorecardParams {
  /** Inclusive ISO date (YYYY-MM-DD). Defaults to 30 days ago server-side. */
  start_date?: string;
  /** Inclusive ISO date (YYYY-MM-DD). Defaults to today server-side. */
  end_date?: string;
}

export const scorecardApi = {
  get: async (
    workspaceId: string,
    params: ScorecardParams = {},
  ): Promise<ReceptionistScorecard> => {
    return apiGet<ReceptionistScorecard>(`/api/v1/workspaces/${workspaceId}/scorecard`, { params });
  },
  getTechnicians: async (
    workspaceId: string,
    params: ScorecardParams = {},
  ): Promise<TechnicianActivityScorecardRow[]> => {
    return apiGet<TechnicianActivityScorecardRow[]>(
      `/api/v1/workspaces/${workspaceId}/scorecard/technicians`,
      { params },
    );
  },
  getOfficeReps: async (
    workspaceId: string,
    params: ScorecardParams = {},
  ): Promise<OfficeRepScorecardRow[]> => {
    return apiGet<OfficeRepScorecardRow[]>(
      `/api/v1/workspaces/${workspaceId}/scorecard/office-reps`,
      { params },
    );
  },
};
