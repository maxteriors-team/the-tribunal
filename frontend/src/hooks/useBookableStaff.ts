import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  bookableStaffApi,
  type BookableStaffList,
  type CreateBookableStaffRequest,
  type UpdateBookableStaffRequest,
} from "@/lib/api/bookable-staff";

const bookableStaffKey = (workspaceId: string, agentId: string) =>
  ["bookableStaff", workspaceId, agentId] as const;

/** List the bookable staff in an agent's assignment pool. */
export function useBookableStaff(workspaceId: string, agentId: string, enabled = true) {
  return useQuery<BookableStaffList>({
    queryKey: bookableStaffKey(workspaceId, agentId),
    queryFn: () => bookableStaffApi.list(workspaceId, agentId),
    enabled: enabled && Boolean(workspaceId) && Boolean(agentId),
  });
}

export function useCreateBookableStaff(workspaceId: string, agentId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: CreateBookableStaffRequest) =>
      bookableStaffApi.create(workspaceId, agentId, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: bookableStaffKey(workspaceId, agentId) });
    },
  });
}

export function useUpdateBookableStaff(workspaceId: string, agentId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ staffId, body }: { staffId: string; body: UpdateBookableStaffRequest }) =>
      bookableStaffApi.update(workspaceId, agentId, staffId, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: bookableStaffKey(workspaceId, agentId) });
    },
  });
}

export function useDeleteBookableStaff(workspaceId: string, agentId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (staffId: string) => bookableStaffApi.remove(workspaceId, agentId, staffId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: bookableStaffKey(workspaceId, agentId) });
    },
  });
}
