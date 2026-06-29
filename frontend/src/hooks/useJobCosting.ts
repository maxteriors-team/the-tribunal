import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  jobsApi,
  type ClockInRequest,
  type JobExpense,
  type JobExpenseCreate,
  type JobProfitability,
  type TimeEntry,
  type TimeEntryCreate,
} from "@/lib/api/jobs";
import { queryKeys } from "@/lib/query-keys";

/** A job's time entries (clock-ins and manual spans), newest first. */
export function useJobTimeEntries(workspaceId: string, jobId: string, enabled = true) {
  return useQuery<TimeEntry[]>({
    queryKey: queryKeys.jobs.timeEntries(workspaceId, jobId),
    queryFn: () => jobsApi.listTimeEntries(workspaceId, jobId),
    enabled: enabled && Boolean(workspaceId && jobId),
  });
}

/** A job's expenses, newest first. */
export function useJobExpenses(workspaceId: string, jobId: string, enabled = true) {
  return useQuery<JobExpense[]>({
    queryKey: queryKeys.jobs.expenses(workspaceId, jobId),
    queryFn: () => jobsApi.listExpenses(workspaceId, jobId),
    enabled: enabled && Boolean(workspaceId && jobId),
  });
}

/** A job's computed P&L (revenue from the linked invoice minus labor + expenses). */
export function useJobProfitability(workspaceId: string, jobId: string, enabled = true) {
  return useQuery<JobProfitability>({
    queryKey: queryKeys.jobs.profitability(workspaceId, jobId),
    queryFn: () => jobsApi.profitability(workspaceId, jobId),
    enabled: enabled && Boolean(workspaceId && jobId),
  });
}

/**
 * Invalidate every costing query for a job — time entries, expenses, and the
 * derived P&L all move together whenever any of them changes.
 */
function useCostingInvalidation(workspaceId: string, jobId: string) {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({
      queryKey: queryKeys.jobs.timeEntries(workspaceId, jobId),
    });
    void queryClient.invalidateQueries({
      queryKey: queryKeys.jobs.expenses(workspaceId, jobId),
    });
    void queryClient.invalidateQueries({
      queryKey: queryKeys.jobs.profitability(workspaceId, jobId),
    });
  };
}

export function useClockIn(workspaceId: string, jobId: string) {
  const invalidate = useCostingInvalidation(workspaceId, jobId);
  return useMutation({
    mutationFn: (body: ClockInRequest = { rate: 0 }) => jobsApi.clockIn(workspaceId, jobId, body),
    onSuccess: invalidate,
  });
}

export function useClockOut(workspaceId: string, jobId: string) {
  const invalidate = useCostingInvalidation(workspaceId, jobId);
  return useMutation({
    mutationFn: () => jobsApi.clockOut(workspaceId, jobId),
    onSuccess: invalidate,
  });
}

export function useAddTimeEntry(workspaceId: string, jobId: string) {
  const invalidate = useCostingInvalidation(workspaceId, jobId);
  return useMutation({
    mutationFn: (body: TimeEntryCreate) => jobsApi.addTimeEntry(workspaceId, jobId, body),
    onSuccess: invalidate,
  });
}

export function useDeleteTimeEntry(workspaceId: string, jobId: string) {
  const invalidate = useCostingInvalidation(workspaceId, jobId);
  return useMutation({
    mutationFn: (entryId: string) => jobsApi.deleteTimeEntry(workspaceId, jobId, entryId),
    onSuccess: invalidate,
  });
}

export function useAddExpense(workspaceId: string, jobId: string) {
  const invalidate = useCostingInvalidation(workspaceId, jobId);
  return useMutation({
    mutationFn: (body: JobExpenseCreate) => jobsApi.addExpense(workspaceId, jobId, body),
    onSuccess: invalidate,
  });
}

export function useDeleteExpense(workspaceId: string, jobId: string) {
  const invalidate = useCostingInvalidation(workspaceId, jobId);
  return useMutation({
    mutationFn: (expenseId: string) => jobsApi.deleteExpense(workspaceId, jobId, expenseId),
    onSuccess: invalidate,
  });
}
