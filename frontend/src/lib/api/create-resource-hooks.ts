/**
 * Generic React Query hook generator for CRUD resources.
 * Generates useList, useGet, useCreate, useUpdate, useDelete hooks from an API client.
 */

import { useQuery, useMutation, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import type { PaginatedResponse, ResourceId } from "@/types/api";
import type { ApiClient } from "./create-api-client";

/**
 * Options for creating resource hooks.
 */
export interface CreateResourceHooksOptions<T, CreateData, UpdateData> {
  /**
   * The resource key used for query keys (e.g., "tags", "segments").
   */
  resourceKey: string;

  /**
   * The API client with CRUD methods.
   */
  apiClient: ApiClient<T, CreateData, UpdateData>;

  /**
   * Additional query keys to invalidate on mutations.
   * Useful for invalidating related resources (e.g., invalidate "contacts" when updating "tags").
   */
  invalidateKeys?: string[];

  /**
   * Whether to generate the useList hook. Default: true.
   */
  includeList?: boolean;

  /**
   * Whether to generate the useGet hook. Default: true.
   */
  includeGet?: boolean;

  /**
   * Whether to generate the useCreate hook. Default: true.
   */
  includeCreate?: boolean;

  /**
   * Whether to generate the useUpdate hook. Default: true.
   */
  includeUpdate?: boolean;

  /**
   * Whether to generate the useDelete hook. Default: true.
   */
  includeDelete?: boolean;
}

/**
 * Query key helpers for a resource.
 */
export interface ResourceQueryKeys {
  list: (workspaceId: string, params?: Record<string, unknown>) => readonly unknown[];
  get: (workspaceId: string, id: ResourceId) => readonly unknown[];
  all: (workspaceId: string) => readonly unknown[];
}

/**
 * Generated resource hooks.
 */
export interface ResourceHooks<T, CreateData, UpdateData> {
  queryKeys: ResourceQueryKeys;
  useList: (workspaceId: string, params?: Record<string, unknown>) => UseQueryResult<PaginatedResponse<T>>;
  useGet: (workspaceId: string, id: ResourceId) => UseQueryResult<T>;
  useCreate: (workspaceId: string) => ReturnType<typeof useMutation<T, Error, CreateData>>;
  useUpdate: (workspaceId: string) => ReturnType<typeof useMutation<T, Error, { id: ResourceId; data: UpdateData }>>;
  useDelete: (workspaceId: string) => ReturnType<typeof useMutation<void, Error, ResourceId>>;
}

/**
 * Creates a set of React Query hooks for a resource.
 *
 * @example
 * ```ts
 * import { createResourceHooks } from "@/lib/api/create-resource-hooks";
 * import { tagsApi } from "@/lib/api/tags";
 *
 * export const {
 *   queryKeys: tagQueryKeys,
 *   useList: useTags,
 *   useGet: useTag,
 *   useCreate: useCreateTag,
 *   useUpdate: useUpdateTag,
 *   useDelete: useDeleteTag,
 * } = createResourceHooks({
 *   resourceKey: "tags",
 *   apiClient: tagsApi,
 *   invalidateKeys: ["contacts"], // Invalidate contacts when tags change
 * });
 * ```
 */
export function createResourceHooks<T, CreateData, UpdateData>(
  options: CreateResourceHooksOptions<T, CreateData, UpdateData>
): ResourceHooks<T, CreateData, UpdateData> {
  const {
    resourceKey,
    apiClient,
    invalidateKeys = [],
    includeList = true,
    includeGet = true,
    includeCreate = true,
    includeUpdate = true,
    includeDelete = true,
  } = options;

  // Build query key arrays
  const queryKeys: ResourceQueryKeys = {
    list: (workspaceId: string, params?: Record<string, unknown>) => {
      const baseKey = [resourceKey, workspaceId] as const;
      return params ? [...baseKey, params] : baseKey;
    },
    get: (workspaceId: string, id: ResourceId) => [resourceKey, workspaceId, id] as const,
    all: (workspaceId: string) => [resourceKey, workspaceId] as const,
  };

  // Build invalidate keys
  const buildInvalidateKeys = (workspaceId: string) => {
    const keys: unknown[][] = [];
    // Invalidate the resource itself
    keys.push([resourceKey, workspaceId]);
    // Invalidate single item queries for this resource
    keys.push([resourceKey]);
    // Invalidate additional keys
    for (const key of invalidateKeys) {
      keys.push([key, workspaceId]);
    }
    return keys;
  };

  const hooks: ResourceHooks<T, CreateData, UpdateData> = {
    queryKeys,

    useList: (workspaceId: string, params?: Record<string, unknown>): UseQueryResult<PaginatedResponse<T>> => {
      return useQuery({
        queryKey: queryKeys.list(workspaceId, params),
        queryFn: () => apiClient.list(workspaceId, params),
        enabled: !!workspaceId,
      });
    },

    useGet: (workspaceId: string, id: ResourceId): UseQueryResult<T> => {
      return useQuery({
        queryKey: queryKeys.get(workspaceId, id),
        queryFn: () => {
          if (!apiClient.get) {
            throw new Error(`API client for ${resourceKey} does not have a 'get' method`);
          }
          return apiClient.get(workspaceId, id);
        },
        enabled: !!workspaceId && id !== undefined && id !== null,
      });
    },

    useCreate: (workspaceId: string) => {
      const queryClient = useQueryClient();

      return useMutation({
        mutationFn: (data: CreateData) => {
          if (!apiClient.create) {
            throw new Error(`API client for ${resourceKey} does not have a 'create' method`);
          }
          return apiClient.create(workspaceId, data);
        },
        onSuccess: () => {
          const keys = buildInvalidateKeys(workspaceId);
          for (const key of keys) {
            queryClient.invalidateQueries({ queryKey: key });
          }
        },
      });
    },

    useUpdate: (workspaceId: string) => {
      const queryClient = useQueryClient();

      return useMutation({
        mutationFn: (variables: { id: ResourceId; data: UpdateData }) => {
          if (!apiClient.update) {
            throw new Error(`API client for ${resourceKey} does not have an 'update' method`);
          }
          return apiClient.update(workspaceId, variables.id, variables.data);
        },
        onSuccess: () => {
          const keys = buildInvalidateKeys(workspaceId);
          for (const key of keys) {
            queryClient.invalidateQueries({ queryKey: key });
          }
        },
      });
    },

    useDelete: (workspaceId: string) => {
      const queryClient = useQueryClient();

      return useMutation({
        mutationFn: (id: ResourceId) => {
          if (!apiClient.delete) {
            throw new Error(`API client for ${resourceKey} does not have a 'delete' method`);
          }
          return apiClient.delete(workspaceId, id);
        },
        onSuccess: () => {
          const keys = buildInvalidateKeys(workspaceId);
          for (const key of keys) {
            queryClient.invalidateQueries({ queryKey: key });
          }
        },
      });
    },
  };

  // Remove hooks that were not requested
  if (!includeList) {
    delete (hooks as Partial<ResourceHooks<T, CreateData, UpdateData>>).useList;
  }
  if (!includeGet) {
    delete (hooks as Partial<ResourceHooks<T, CreateData, UpdateData>>).useGet;
  }
  if (!includeCreate) {
    delete (hooks as Partial<ResourceHooks<T, CreateData, UpdateData>>).useCreate;
  }
  if (!includeUpdate) {
    delete (hooks as Partial<ResourceHooks<T, CreateData, UpdateData>>).useUpdate;
  }
  if (!includeDelete) {
    delete (hooks as Partial<ResourceHooks<T, CreateData, UpdateData>>).useDelete;
  }

  return hooks;
}
