/**
 * Field-service job dispatch API, typed straight from the OpenAPI spec.
 *
 * A *job* is a unit of field work for a customer; technicians are tagged onto it
 * and each assigned worker sees it on their calendar (`/calendar/mine`).
 */

import { apiClient, type Schemas } from "@/lib/api/_client";
import type {
  CompleteJobInventoryRequest,
  InventoryJobAllocation,
  JobInventoryPlan,
} from "@/types/inventory";

export type Job = Schemas["JobResponse"];
export type JobList = Schemas["JobListResponse"];
export type JobStatus = Schemas["JobStatus"];
export type JobCreateRequest = Schemas["JobCreate"];
export type JobUpdateRequest = Schemas["JobUpdate"];
export type JobScheduleRequest = Schemas["JobScheduleRequest"];
export type JobAssignRequest = Schemas["JobAssignRequest"];
export type JobTechnician = Schemas["TechnicianSummary"];
export type JobCrew = Schemas["CrewResponse"];
export type JobCrewList = Schemas["CrewListResponse"];
export type JobInstallationPlan = Schemas["JobInstallationPlanResponse"];
export type JobVisit = Schemas["JobVisitResponse"];
export type JobVisitCreate = Schemas["JobVisitCreate"];
export type JobVisitUpdate = Schemas["JobVisitUpdate"];
export type JobPricing = Schemas["JobPricingResponse"];
export type JobPricingReplace = Schemas["JobPricingReplace"];

// Field execution: time tracking, expenses, profitability.
export type TimeEntry = Schemas["TimeEntryResponse"];
export type ClockInRequest = Schemas["ClockInRequest"];
export type TimeEntryCreate = Schemas["TimeEntryCreate"];
export type JobExpense = Schemas["JobExpenseResponse"];
export type JobExpenseCreate = Schemas["JobExpenseCreate"];
export type JobProfitability = Schemas["JobProfitability"];

// Neighbor outreach: the street around a finished job.
export type NeighborBatch = Schemas["NeighborOutreachBatchResponse"];
export type NeighborEntry = Schemas["NeighborOutreachEntryResponse"];
export type NeighborStatus = Schemas["NeighborOutreachStatus"];
export type NeighborChannel = Schemas["NeighborOutreachChannel"];
export type NeighborGenerateRequest = Schemas["NeighborOutreachGenerateRequest"];
export type NeighborEntryUpdate = Schemas["NeighborOutreachEntryUpdate"];
export type NeighborExport = Schemas["NeighborOutreachExportResponse"];
export type NeighborExportRow = Schemas["NeighborOutreachExportRow"];
export type NeighborCampaignRequest = Schemas["NeighborOutreachCampaignRequest"];
export type NeighborCampaignResult = Schemas["NeighborOutreachCampaignResponse"];

export interface JobListParams {
  status?: JobStatus;
  crew_id?: string;
  business_location_id?: string;
  technician_id?: string;
  date_from?: string;
  date_to?: string;
  /**
   * Narrow the result to the caller's own work. Below the dispatch tier the
   * server applies this regardless; a dispatcher sets it to filter their board
   * down to what they are personally on.
   */
  mine?: boolean;
}

export interface JobCalendarParams {
  date_from?: string;
  date_to?: string;
}

const BASE = "/api/v1/workspaces/{workspace_id}/jobs" as const;

export const jobsApi = {
  list: (workspaceId: string, query: JobListParams = {}): Promise<JobList> =>
    apiClient.get(BASE, { path: { workspace_id: workspaceId }, query }),

  listCrews: (workspaceId: string): Promise<JobCrewList> =>
    apiClient.get("/api/v1/workspaces/{workspace_id}/crews", {
      path: { workspace_id: workspaceId },
    }),

  /** Jobs assigned to the signed-in user, for their own calendar. */
  listMine: (workspaceId: string, query: JobCalendarParams = {}): Promise<JobList> =>
    apiClient.get("/api/v1/workspaces/{workspace_id}/jobs/calendar/mine", {
      path: { workspace_id: workspaceId },
      query,
    }),

  get: (workspaceId: string, jobId: string): Promise<Job> =>
    apiClient.get("/api/v1/workspaces/{workspace_id}/jobs/{job_id}", {
      path: { workspace_id: workspaceId, job_id: jobId },
    }),

  installationPlan: (workspaceId: string, jobId: string): Promise<JobInstallationPlan> =>
    apiClient.get("/api/v1/workspaces/{workspace_id}/jobs/{job_id}/installation-plan", {
      path: { workspace_id: workspaceId, job_id: jobId },
    }),

  inventoryPlan: (workspaceId: string, jobId: string): Promise<JobInventoryPlan> =>
    apiClient.get("/api/v1/workspaces/{workspace_id}/jobs/{job_id}/inventory-plan", {
      path: { workspace_id: workspaceId, job_id: jobId },
    }),

  completeWithInventory: (
    workspaceId: string,
    jobId: string,
    body: CompleteJobInventoryRequest,
  ): Promise<JobInventoryPlan> =>
    apiClient.post("/api/v1/workspaces/{workspace_id}/jobs/{job_id}/complete-with-inventory", {
      path: { workspace_id: workspaceId, job_id: jobId },
      body,
    }),

  returnInventoryAllocation: (
    workspaceId: string,
    jobId: string,
    allocationId: string,
  ): Promise<InventoryJobAllocation> =>
    apiClient.post(
      "/api/v1/workspaces/{workspace_id}/jobs/{job_id}/inventory-allocations/{allocation_id}/return",
      {
        path: { workspace_id: workspaceId, job_id: jobId, allocation_id: allocationId },
      },
    ),

  listVisits: (workspaceId: string, jobId: string): Promise<JobVisit[]> =>
    apiClient.get("/api/v1/workspaces/{workspace_id}/jobs/{job_id}/visits", {
      path: { workspace_id: workspaceId, job_id: jobId },
    }),

  createVisit: (workspaceId: string, jobId: string, body: JobVisitCreate): Promise<JobVisit> =>
    apiClient.post("/api/v1/workspaces/{workspace_id}/jobs/{job_id}/visits", {
      path: { workspace_id: workspaceId, job_id: jobId },
      body,
    }),

  updateVisit: (
    workspaceId: string,
    jobId: string,
    visitId: string,
    body: JobVisitUpdate,
  ): Promise<JobVisit> =>
    apiClient.patch("/api/v1/workspaces/{workspace_id}/jobs/{job_id}/visits/{visit_id}", {
      path: { workspace_id: workspaceId, job_id: jobId, visit_id: visitId },
      body,
    }),

  deleteVisit: (workspaceId: string, jobId: string, visitId: string): Promise<void> =>
    apiClient.del("/api/v1/workspaces/{workspace_id}/jobs/{job_id}/visits/{visit_id}", {
      path: { workspace_id: workspaceId, job_id: jobId, visit_id: visitId },
    }),

  getPricing: (workspaceId: string, jobId: string): Promise<JobPricing> =>
    apiClient.get("/api/v1/workspaces/{workspace_id}/jobs/{job_id}/pricing", {
      path: { workspace_id: workspaceId, job_id: jobId },
    }),

  replacePricing: (
    workspaceId: string,
    jobId: string,
    body: JobPricingReplace,
  ): Promise<JobPricing> =>
    apiClient.put("/api/v1/workspaces/{workspace_id}/jobs/{job_id}/pricing", {
      path: { workspace_id: workspaceId, job_id: jobId },
      body,
    }),

  create: (workspaceId: string, body: JobCreateRequest): Promise<Job> =>
    apiClient.post(BASE, { path: { workspace_id: workspaceId }, body }),

  update: (workspaceId: string, jobId: string, body: JobUpdateRequest): Promise<Job> =>
    apiClient.patch("/api/v1/workspaces/{workspace_id}/jobs/{job_id}", {
      path: { workspace_id: workspaceId, job_id: jobId },
      body,
    }),

  remove: (workspaceId: string, jobId: string): Promise<void> =>
    apiClient.del("/api/v1/workspaces/{workspace_id}/jobs/{job_id}", {
      path: { workspace_id: workspaceId, job_id: jobId },
    }),

  schedule: (workspaceId: string, jobId: string, body: JobScheduleRequest): Promise<Job> =>
    apiClient.post("/api/v1/workspaces/{workspace_id}/jobs/{job_id}/schedule", {
      path: { workspace_id: workspaceId, job_id: jobId },
      body,
    }),

  assign: (workspaceId: string, jobId: string, body: JobAssignRequest): Promise<Job> =>
    apiClient.post("/api/v1/workspaces/{workspace_id}/jobs/{job_id}/assignments", {
      path: { workspace_id: workspaceId, job_id: jobId },
      body,
    }),

  unassign: (workspaceId: string, jobId: string, technicianId: string): Promise<Job> =>
    apiClient.del("/api/v1/workspaces/{workspace_id}/jobs/{job_id}/assignments/{technician_id}", {
      path: { workspace_id: workspaceId, job_id: jobId, technician_id: technicianId },
    }),

  // ----- Field execution: time tracking, expenses, profitability ----- //
  listTimeEntries: (workspaceId: string, jobId: string): Promise<TimeEntry[]> =>
    apiClient.get("/api/v1/workspaces/{workspace_id}/jobs/{job_id}/time-entries", {
      path: { workspace_id: workspaceId, job_id: jobId },
    }),

  clockIn: (
    workspaceId: string,
    jobId: string,
    body: ClockInRequest = { rate: 0 },
  ): Promise<TimeEntry> =>
    apiClient.post("/api/v1/workspaces/{workspace_id}/jobs/{job_id}/time-entries/clock-in", {
      path: { workspace_id: workspaceId, job_id: jobId },
      body,
    }),

  pauseTimer: (workspaceId: string, jobId: string): Promise<TimeEntry> =>
    apiClient.post("/api/v1/workspaces/{workspace_id}/jobs/{job_id}/time-entries/pause", {
      path: { workspace_id: workspaceId, job_id: jobId },
    }),

  endTimer: (workspaceId: string, jobId: string): Promise<TimeEntry> =>
    apiClient.post("/api/v1/workspaces/{workspace_id}/jobs/{job_id}/time-entries/end", {
      path: { workspace_id: workspaceId, job_id: jobId },
    }),

  /** Compatibility for older callers; clock-out now pauses the timer. */
  clockOut: (workspaceId: string, jobId: string): Promise<TimeEntry> =>
    apiClient.post("/api/v1/workspaces/{workspace_id}/jobs/{job_id}/time-entries/clock-out", {
      path: { workspace_id: workspaceId, job_id: jobId },
    }),

  addTimeEntry: (workspaceId: string, jobId: string, body: TimeEntryCreate): Promise<TimeEntry> =>
    apiClient.post("/api/v1/workspaces/{workspace_id}/jobs/{job_id}/time-entries", {
      path: { workspace_id: workspaceId, job_id: jobId },
      body,
    }),

  deleteTimeEntry: (workspaceId: string, jobId: string, entryId: string): Promise<void> =>
    apiClient.del("/api/v1/workspaces/{workspace_id}/jobs/{job_id}/time-entries/{entry_id}", {
      path: { workspace_id: workspaceId, job_id: jobId, entry_id: entryId },
    }),

  listExpenses: (workspaceId: string, jobId: string): Promise<JobExpense[]> =>
    apiClient.get("/api/v1/workspaces/{workspace_id}/jobs/{job_id}/expenses", {
      path: { workspace_id: workspaceId, job_id: jobId },
    }),

  addExpense: (workspaceId: string, jobId: string, body: JobExpenseCreate): Promise<JobExpense> =>
    apiClient.post("/api/v1/workspaces/{workspace_id}/jobs/{job_id}/expenses", {
      path: { workspace_id: workspaceId, job_id: jobId },
      body,
    }),

  deleteExpense: (workspaceId: string, jobId: string, expenseId: string): Promise<void> =>
    apiClient.del("/api/v1/workspaces/{workspace_id}/jobs/{job_id}/expenses/{expense_id}", {
      path: { workspace_id: workspaceId, job_id: jobId, expense_id: expenseId },
    }),

  profitability: (workspaceId: string, jobId: string): Promise<JobProfitability> =>
    apiClient.get("/api/v1/workspaces/{workspace_id}/jobs/{job_id}/profitability", {
      path: { workspace_id: workspaceId, job_id: jobId },
    }),

  // ----- Neighbor outreach ----- //
  /** The generated neighbour list for a job. Rejects with 404 until generated. */
  neighbors: (workspaceId: string, jobId: string): Promise<NeighborBatch> =>
    apiClient.get("/api/v1/workspaces/{workspace_id}/jobs/{job_id}/neighbors", {
      path: { workspace_id: workspaceId, job_id: jobId },
    }),

  /** Generate or top up the list. Idempotent — existing statuses are preserved. */
  generateNeighbors: (
    workspaceId: string,
    jobId: string,
    body: NeighborGenerateRequest = {},
  ): Promise<NeighborBatch> =>
    apiClient.post("/api/v1/workspaces/{workspace_id}/jobs/{job_id}/neighbors", {
      path: { workspace_id: workspaceId, job_id: jobId },
      body,
    }),

  /** Door-hanger / direct-mail rows, including each neighbour's postal address. */
  neighborsExport: (workspaceId: string, jobId: string): Promise<NeighborExport> =>
    apiClient.get("/api/v1/workspaces/{workspace_id}/jobs/{job_id}/neighbors/export", {
      path: { workspace_id: workspaceId, job_id: jobId },
    }),

  updateNeighborEntry: (
    workspaceId: string,
    jobId: string,
    entryId: string,
    body: NeighborEntryUpdate,
  ): Promise<NeighborEntry> =>
    apiClient.patch(
      "/api/v1/workspaces/{workspace_id}/jobs/{job_id}/neighbors/entries/{entry_id}",
      {
        path: { workspace_id: workspaceId, job_id: jobId, entry_id: entryId },
        body,
      },
    ),

  /** Enroll the consented subset of the batch into an existing campaign. */
  enrollNeighbors: (
    workspaceId: string,
    jobId: string,
    body: NeighborCampaignRequest,
  ): Promise<NeighborCampaignResult> =>
    apiClient.post("/api/v1/workspaces/{workspace_id}/jobs/{job_id}/neighbors/campaign", {
      path: { workspace_id: workspaceId, job_id: jobId },
      body,
    }),
};
