import { useQuery } from "@tanstack/react-query";
import { createResourceHooks } from "@/lib/api/create-resource-hooks";
import { segmentsApi } from "@/lib/api/segments";
import { queryKeys } from "@/lib/query-keys";

const {
  queryKeys: segmentQueryKeys,
  useList: useSegments,
  useGet: useSegment,
  useCreate: useCreateSegment,
  useUpdate: useUpdateSegment,
  useDelete: useDeleteSegment,
} = createResourceHooks({
  resourceKey: "segments",
  apiClient: segmentsApi,
});

export { segmentQueryKeys, useSegments, useSegment, useCreateSegment, useUpdateSegment, useDeleteSegment };

export function useSegmentContacts(workspaceId: string, segmentId: string) {
  return useQuery({
    queryKey: queryKeys.segments.contacts(workspaceId, segmentId),
    queryFn: () => segmentsApi.getContacts(workspaceId, segmentId),
    enabled: !!workspaceId && !!segmentId,
  });
}
