import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient, type Schemas } from "@/lib/api/_client";
import {
  jobsApi,
  type JobAssignRequest,
  type JobCreateRequest,
  type JobCrewList,
  type JobInstallationPlan,
  type JobList,
  type JobListParams,
  type JobPricing,
  type JobPricingReplace,
  type JobScheduleRequest,
  type JobUpdateRequest,
  type JobVisit,
  type JobVisitCreate,
  type JobVisitUpdate,
} from "@/lib/api/jobs";
import { queryKeys } from "@/lib/query-keys";

/** Schedule-grid colour the backend also defaults to for a new technician. */
const DEFAULT_TECHNICIAN_COLOR = "#0ea5e9";

/** List jobs for the dispatch board / calendar, scoped to the active week + filters. */
export function useJobs(workspaceId: string, params: JobListParams = {}, enabled = true) {
  return useQuery<JobList>({
    queryKey: queryKeys.jobs.list(workspaceId, params as Record<string, unknown>),
    queryFn: () => jobsApi.list(workspaceId, params),
    enabled: enabled && Boolean(workspaceId),
  });
}

/** Load one authoritative job, including jobs outside the visible calendar week. */
export function useJob(workspaceId: string, jobId: string, enabled = true) {
  return useQuery<Schemas["JobResponse"]>({
    queryKey: queryKeys.jobs.detail(workspaceId, jobId),
    queryFn: () => jobsApi.get(workspaceId, jobId),
    enabled: enabled && Boolean(workspaceId) && Boolean(jobId),
    retry: false,
  });
}

/** Assignment-scoped read-only installation copy for a job detail dialog. */
export function useJobInstallationPlan(workspaceId: string, jobId: string, enabled = true) {
  return useQuery<JobInstallationPlan>({
    queryKey: queryKeys.jobs.installationPlan(workspaceId, jobId),
    queryFn: () => jobsApi.installationPlan(workspaceId, jobId),
    enabled: enabled && Boolean(workspaceId) && Boolean(jobId),
    retry: false,
  });
}

export function useJobVisits(workspaceId: string, jobId: string, enabled = true) {
  return useQuery<JobVisit[]>({
    queryKey: queryKeys.jobs.visits(workspaceId, jobId),
    queryFn: () => jobsApi.listVisits(workspaceId, jobId),
    enabled: enabled && Boolean(workspaceId) && Boolean(jobId),
    retry: false,
  });
}

export function useCreateJobVisit(workspaceId: string, jobId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: JobVisitCreate) => jobsApi.createVisit(workspaceId, jobId, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.jobs.visits(workspaceId, jobId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.jobs.all(workspaceId) });
    },
  });
}

export function useUpdateJobVisit(workspaceId: string, jobId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ visitId, body }: { visitId: string; body: JobVisitUpdate }) =>
      jobsApi.updateVisit(workspaceId, jobId, visitId, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.jobs.visits(workspaceId, jobId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.jobs.all(workspaceId) });
    },
  });
}

export function useDeleteJobVisit(workspaceId: string, jobId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (visitId: string) => jobsApi.deleteVisit(workspaceId, jobId, visitId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.jobs.visits(workspaceId, jobId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.jobs.all(workspaceId) });
    },
  });
}

export function useJobPricing(workspaceId: string, jobId: string, enabled = true) {
  return useQuery<JobPricing>({
    queryKey: queryKeys.jobs.pricing(workspaceId, jobId),
    queryFn: () => jobsApi.getPricing(workspaceId, jobId),
    enabled: enabled && Boolean(workspaceId) && Boolean(jobId),
    retry: false,
  });
}

export function useReplaceJobPricing(workspaceId: string, jobId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: JobPricingReplace) => jobsApi.replacePricing(workspaceId, jobId, body),
    onSuccess: (pricing) => {
      queryClient.setQueryData(queryKeys.jobs.pricing(workspaceId, jobId), pricing);
    },
  });
}

/** Active workspace crews for routing the installation team. */
export function useWorkspaceCrews(workspaceId: string, enabled = true) {
  return useQuery<JobCrewList>({
    queryKey: queryKeys.jobs.crews(workspaceId),
    queryFn: () => jobsApi.listCrews(workspaceId),
    enabled: enabled && Boolean(workspaceId),
  });
}

/** Workspace technicians, for the "tag workers" multi-select. */
export function useWorkspaceTechnicians(workspaceId: string, enabled = true) {
  return useQuery<Schemas["TechnicianListResponse"]>({
    queryKey: queryKeys.technicians.active(workspaceId),
    queryFn: () =>
      apiClient.get("/api/v1/workspaces/{workspace_id}/technicians", {
        path: { workspace_id: workspaceId },
        query: { is_active: true },
      }),
    enabled: enabled && Boolean(workspaceId),
  });
}

/**
 * The whole roster, retired entries included — unlike
 * {@link useWorkspaceTechnicians}, which feeds the assignment picker. Team
 * settings needs the retired rows too, so putting someone back on the board
 * reuses their entry instead of creating a second one.
 */
export function useWorkspaceRoster(workspaceId: string, enabled = true) {
  return useQuery<Schemas["TechnicianListResponse"]>({
    queryKey: queryKeys.technicians.list(workspaceId),
    queryFn: () =>
      apiClient.get("/api/v1/workspaces/{workspace_id}/technicians", {
        path: { workspace_id: workspaceId },
      }),
    enabled: enabled && Boolean(workspaceId),
  });
}

interface RosterToggleInput {
  /** Existing roster entry for this member, when they already have one. */
  technicianId?: string;
  /** Login to link, so the technician sees their own jobs when they sign in. */
  userId: number;
  name: string;
  email?: string | null;
  onRoster: boolean;
}

/**
 * Put a workspace member on the dispatch roster, or retire them from it.
 *
 * Members holding a field role are added automatically when they join (backend
 * `app.services.field_service.roster`); this is the manual override for anyone
 * else who works jobs — an owner who still runs a truck, a manager covering a
 * route. Retiring deactivates the entry rather than deleting it, keeping the
 * job history of everything they already worked.
 */
export function useSetMemberOnRoster(workspaceId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ technicianId, userId, name, email, onRoster }: RosterToggleInput) =>
      technicianId
        ? apiClient.put("/api/v1/workspaces/{workspace_id}/technicians/{technician_id}", {
            path: { workspace_id: workspaceId, technician_id: technicianId },
            body: { is_active: onRoster },
          })
        : apiClient.post("/api/v1/workspaces/{workspace_id}/technicians", {
            path: { workspace_id: workspaceId },
            body: {
              name,
              email: email ?? null,
              user_id: userId,
              is_active: true,
              scoreboard_enabled: true,
              color: DEFAULT_TECHNICIAN_COLOR,
            },
          }),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.technicians.all(workspaceId),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.technicianScoreboard.all(workspaceId),
      });
    },
  });
}

interface LeagueToggleInput {
  technicianId: string;
  enabled: boolean;
}

/** Include or hide one rostered member without deleting their earned XP history. */
export function useSetMemberInLeague(workspaceId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ technicianId, enabled }: LeagueToggleInput) =>
      apiClient.put("/api/v1/workspaces/{workspace_id}/technicians/{technician_id}", {
        path: { workspace_id: workspaceId, technician_id: technicianId },
        body: { scoreboard_enabled: enabled },
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.technicians.all(workspaceId),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.technicianScoreboard.all(workspaceId),
      });
    },
  });
}

/**
 * Whether each member has a booking calendar (a linked `bookable_staff` row).
 *
 * Dispatch-tier users read this roster for schedule tagging. Team-settings
 * mutations remain gated on `members:manage` server-side.
 */
export function useWorkspaceBookableStaff(workspaceId: string, enabled = true) {
  return useQuery<Schemas["BookableStaffList"]>({
    queryKey: queryKeys.bookableStaff.all(workspaceId),
    queryFn: () =>
      apiClient.get("/api/v1/workspaces/{workspace_id}/bookable-staff", {
        path: { workspace_id: workspaceId },
      }),
    enabled: enabled && Boolean(workspaceId),
  });
}

interface BookableToggleInput {
  userId: number;
  name: string;
  email?: string | null;
  bookable: boolean;
}

/**
 * Enable or disable a member's booking resources from Settings → Team.
 *
 * Disabling preserves staff links and appointment history, so enabling again
 * restores the same resources. Sits beside {@link useSetMemberOnRoster}: one
 * screen decides both whether
 * someone can be dispatched to jobs and whether they can be booked for
 * appointments, which are the two halves of what shows on their calendar.
 */
export function useSetMemberBookable(workspaceId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, name, email, bookable }: BookableToggleInput) =>
      apiClient.put("/api/v1/workspaces/{workspace_id}/bookable-staff/members/{user_id}", {
        path: { workspace_id: workspaceId, user_id: userId },
        body: { bookable, name, email: email ?? null },
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.bookableStaff.all(workspaceId),
      });
    },
  });
}

function useJobInvalidation(workspaceId: string) {
  const queryClient = useQueryClient();
  return () => void queryClient.invalidateQueries({ queryKey: queryKeys.jobs.all(workspaceId) });
}

export function useCreateJob(workspaceId: string) {
  const invalidate = useJobInvalidation(workspaceId);
  return useMutation({
    mutationFn: (body: JobCreateRequest) => jobsApi.create(workspaceId, body),
    onSuccess: invalidate,
  });
}

export function useUpdateJob(workspaceId: string) {
  const invalidate = useJobInvalidation(workspaceId);
  return useMutation({
    mutationFn: ({ jobId, body }: { jobId: string; body: JobUpdateRequest }) =>
      jobsApi.update(workspaceId, jobId, body),
    onSuccess: invalidate,
  });
}

export function useScheduleJob(workspaceId: string) {
  const invalidate = useJobInvalidation(workspaceId);
  return useMutation({
    mutationFn: ({ jobId, body }: { jobId: string; body: JobScheduleRequest }) =>
      jobsApi.schedule(workspaceId, jobId, body),
    onSuccess: invalidate,
  });
}

export function useAssignTechnicians(workspaceId: string) {
  const invalidate = useJobInvalidation(workspaceId);
  return useMutation({
    mutationFn: ({ jobId, body }: { jobId: string; body: JobAssignRequest }) =>
      jobsApi.assign(workspaceId, jobId, body),
    onSuccess: invalidate,
  });
}

export function useUnassignTechnician(workspaceId: string) {
  const invalidate = useJobInvalidation(workspaceId);
  return useMutation({
    mutationFn: ({ jobId, technicianId }: { jobId: string; technicianId: string }) =>
      jobsApi.unassign(workspaceId, jobId, technicianId),
    onSuccess: invalidate,
  });
}

export function useDeleteJob(workspaceId: string) {
  const invalidate = useJobInvalidation(workspaceId);
  return useMutation({
    mutationFn: (jobId: string) => jobsApi.remove(workspaceId, jobId),
    onSuccess: invalidate,
  });
}
