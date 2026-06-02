import { useMutation, useQueryClient } from "@tanstack/react-query";

import { createResourceHooks } from "@/lib/api/create-resource-hooks";
import { tagsApi, type BulkTagRequest } from "@/lib/api/tags";
import { queryKeys } from "@/lib/query-keys";

const {
  queryKeys: tagQueryKeys,
  useList: useTags,
  useCreate: useCreateTag,
  useUpdate: useUpdateTag,
  useDelete: useDeleteTag,
} = createResourceHooks({
  resourceKey: "tags",
  apiClient: tagsApi,
  invalidateKeys: ["contacts"],
  includeGet: false,
});

export { tagQueryKeys, useTags, useCreateTag, useUpdateTag, useDeleteTag };

export function useBulkTagContacts(workspaceId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: BulkTagRequest) => tagsApi.bulkTag(workspaceId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.tags.all(workspaceId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.contacts.all(workspaceId) });
    },
  });
}
