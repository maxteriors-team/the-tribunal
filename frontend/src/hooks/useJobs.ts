import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient, type Schemas } from "@/lib/api/_client";
import {
  jobsApi,
  type JobAssignRequest,
  type JobCalendarParams,
  type JobCreateRequest,
  type JobList,
  type JobListParams,
  type JobScheduleRequest,
  type JobUpdateRequest,
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

/** Jobs assigned to the signed-in user — their personal calendar. */
export function useMyJobsCalendar(
  workspaceId: string,
  params: JobCalendarParams = {},
  enabled = true,
) {
  return useQuery<JobList>({
    queryKey: queryKeys.jobs.mine(workspaceId, params as Record<string, unknown>),
    queryFn: () => jobsApi.listMine(workspaceId, params),
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
        ? apiClient.put(
            "/api/v1/workspaces/{workspace_id}/technicians/{technician_id}",
            {
              path: { workspace_id: workspaceId, technician_id: technicianId },
              body: { is_active: onRoster },
            },
          )
        : apiClient.post("/api/v1/workspaces/{workspace_id}/technicians", {
            path: { workspace_id: workspaceId },
            body: {
              name,
              email: email ?? null,
              user_id: userId,
              is_active: true,
              color: DEFAULT_TECHNICIAN_COLOR,
            },
          }),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.technicians.all(workspaceId),
      });
    },
  });
}

function useJobInvalidation(workspaceId: string) {
  const queryClient = useQueryClient();
  return () =>
    void queryClient.invalidateQueries({ queryKey: queryKeys.jobs.all(workspaceId) });
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
