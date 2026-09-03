import { apiGet, apiPost } from "@/lib/api";
import type { components } from "@/lib/api/_generated";

export type TechnicianScoreboard = components["schemas"]["TechnicianScoreboardResponse"];
export type TechnicianScoreboardDetail = components["schemas"]["TechnicianScoreboardDetail"];
export type TechnicianLevelAcknowledgement =
  components["schemas"]["TechnicianLevelAcknowledgementResponse"];

function scoreboardUrl(workspaceId: string, suffix = ""): string {
  return `/api/v1/workspaces/${workspaceId}/technician-scoreboard${suffix}`;
}

export const technicianScoreboardApi = {
  get: (workspaceId: string): Promise<TechnicianScoreboard> => apiGet(scoreboardUrl(workspaceId)),

  detail: (workspaceId: string, technicianId: string): Promise<TechnicianScoreboardDetail> =>
    apiGet(scoreboardUrl(workspaceId, `/technicians/${encodeURIComponent(technicianId)}`)),

  acknowledgeLevel: (workspaceId: string, level: number): Promise<TechnicianLevelAcknowledgement> =>
    apiPost(scoreboardUrl(workspaceId, "/me/acknowledge-level"), { level }),
};
