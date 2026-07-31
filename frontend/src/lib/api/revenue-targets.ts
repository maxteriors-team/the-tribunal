/**
 * Monthly revenue targets and the month-pace report.
 *
 * Targets are addressed by **month**, not by id: `period_month` is any date
 * inside the month and the backend normalizes it to the 1st, so `PUT` is a true
 * idempotent upsert and re-saving a month can never fork it into two rows.
 *
 * Everything goes through the spec-typed client so paths, params and responses
 * are checked against `_generated.ts` rather than re-declared by hand.
 */
import { apiClient, type Schemas } from "@/lib/api/_client";

/** A stored monthly target as returned by the API. */
export type RevenueTarget = Schemas["RevenueTargetResponse"];
/** The client-settable fields of one month, plus the month it belongs to. */
export type RevenueTargetUpsert = Schemas["RevenueTargetUpsert"];
export type RevenueTargetList = Schemas["RevenueTargetList"];
/** One funnel stage's actual-vs-required counts for the month. */
export type PaceStage = Schemas["PaceStage"];
export type PaceStageName = PaceStage["stage"];
/** Whether a month is on pace to hit its revenue goal. */
export type RevenuePace = Schemas["RevenuePace"];

/**
 * The planning fields of a target, without the month or the server-owned
 * columns. This is the unit the settings editor copies between a default plan
 * and a per-month override.
 */
export type RevenueTargetPlan = Omit<
  RevenueTargetUpsert,
  "period_month"
>;

export const revenueTargetsApi = {
  /** List a workspace's targets, oldest month first; `year` narrows to one year. */
  list: (workspaceId: string, year?: number): Promise<RevenueTargetList> =>
    apiClient.get("/api/v1/workspaces/{workspace_id}/revenue-targets", {
      path: { workspace_id: workspaceId },
      query: year === undefined ? {} : { year },
    }),

  /**
   * Report whether a month is on pace to hit its revenue goal.
   *
   * A month with no stored target still reports its actuals, flagged with
   * `has_target: false`, so the dashboard can prompt for a goal instead of
   * rendering an error or a wall of zeros.
   */
  getPace: (workspaceId: string, month?: string): Promise<RevenuePace> =>
    apiClient.get("/api/v1/workspaces/{workspace_id}/revenue-targets/pace", {
      path: { workspace_id: workspaceId },
      query: month === undefined ? {} : { month },
    }),

  /** Set (or replace) one month's target. */
  upsert: (
    workspaceId: string,
    target: RevenueTargetUpsert,
  ): Promise<RevenueTarget> =>
    apiClient.put("/api/v1/workspaces/{workspace_id}/revenue-targets", {
      path: { workspace_id: workspaceId },
      body: target,
    }),

  /**
   * Set a season's worth of targets in one atomic statement.
   *
   * All-or-nothing on the backend, so a rejected month never leaves half a year
   * written. The payload may not name the same month twice.
   */
  bulkUpsert: (
    workspaceId: string,
    targets: RevenueTargetUpsert[],
  ): Promise<RevenueTargetList> =>
    apiClient.put("/api/v1/workspaces/{workspace_id}/revenue-targets/bulk", {
      path: { workspace_id: workspaceId },
      body: { targets },
    }),

  /** Clear one month's target. */
  delete: (workspaceId: string, periodMonth: string): Promise<void> =>
    apiClient.del(
      "/api/v1/workspaces/{workspace_id}/revenue-targets/{period_month}",
      { path: { workspace_id: workspaceId, period_month: periodMonth } },
    ),
};
