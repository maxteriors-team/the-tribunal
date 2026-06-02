import { useMutation, useQueryClient } from "@tanstack/react-query";

import { automationsApi } from "@/lib/api/automations";
import { createResourceHooks } from "@/lib/api/create-resource-hooks";
import { queryKeys } from "@/lib/query-keys";

const {
  queryKeys: automationQueryKeys,
  useList: useAutomations,
  useGet: useAutomation,
  useCreate: useCreateAutomation,
  useUpdate: useUpdateAutomation,
  useDelete: useDeleteAutomation,
} = createResourceHooks({
  resourceKey: "automations",
  apiClient: automationsApi,
});

export {
  automationQueryKeys,
  useAutomations,
  useAutomation,
  useCreateAutomation,
  useUpdateAutomation,
  useDeleteAutomation,
};

export function useToggleAutomation(workspaceId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (automationId: string) =>
      automationsApi.toggle(workspaceId, automationId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.automations.all(workspaceId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.automations.root() });
    },
  });
}
