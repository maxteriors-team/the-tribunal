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
