/**
 * Ad Library prospecting API client.
 *
 * Pull advertisers from public ad libraries (Meta / Google), surface the ones
 * running consistently but not iterating creatives, and ingest qualified
 * advertisers into the CRM. Types are sourced from the generated OpenAPI spec
 * so they stay in lockstep with the backend.
 */

import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";
import { POLL_30S } from "@/lib/query-options";

import type { Schemas } from "./_client";

export type AdLibrarySearchRequest = Schemas["AdLibrarySearchRequest"];
export type AdLibraryJob = Schemas["LeadDiscoveryJobResponse"];
export type AdAdvertiser = Schemas["AdAdvertiserResponse"];
export type AdAdvertiserDetail = Schemas["AdAdvertiserDetail"];
export type AdCreative = Schemas["AdCreativeResponse"];
export type AdSignalBreakdown = Schemas["AdSignalBreakdown"];
export type PaginatedAdAdvertisers = Schemas["PaginatedAdAdvertisers"];
export type AdMonitor = Schemas["AdMonitorResponse"];
export type AdMonitorCreate = Schemas["AdMonitorCreate"];
export type AdMonitorUpdate = Schemas["AdMonitorUpdate"];
export type AdvertiserPromoteRequest = Schemas["AdvertiserPromoteRequest"];
export type AdvertiserPromoteResult = Schemas["AdvertiserPromoteResult"];
export type AdvertiserBulkPromoteRequest = Schemas["AdvertiserBulkPromoteRequest"];
export type AdvertiserBulkPromoteResult = Schemas["AdvertiserBulkPromoteResult"];
export type IcpThresholds = Schemas["IcpThresholds"];

export interface ListAdvertisersParams {
  platform?: "meta" | "google";
  only_qualified?: boolean;
  contact_traced?: boolean;
  page?: number;
  page_size?: number;
}

function advertisersQueryString(params: ListAdvertisersParams): string {
  const search = new URLSearchParams();
  if (params.platform) search.set("platform", params.platform);
  if (params.only_qualified !== undefined)
    search.set("only_qualified", String(params.only_qualified));
  if (params.contact_traced !== undefined)
    search.set("contact_traced", String(params.contact_traced));
  if (params.page !== undefined) search.set("page", String(params.page));
  if (params.page_size !== undefined) search.set("page_size", String(params.page_size));
  const query = search.toString();
  return query ? `?${query}` : "";
}

export const adLibraryApi = {
  search: (workspaceId: string, request: AdLibrarySearchRequest): Promise<AdLibraryJob> =>
    apiPost<AdLibraryJob>(`/api/v1/workspaces/${workspaceId}/ad-library/search`, request),

  getJob: (workspaceId: string, jobId: string): Promise<AdLibraryJob> =>
    apiGet<AdLibraryJob>(`/api/v1/workspaces/${workspaceId}/ad-library/jobs/${jobId}`),

  listAdvertisers: (
    workspaceId: string,
    params: ListAdvertisersParams = {},
  ): Promise<PaginatedAdAdvertisers> =>
    apiGet<PaginatedAdAdvertisers>(
      `/api/v1/workspaces/${workspaceId}/ad-library/advertisers${advertisersQueryString(params)}`,
    ),

  getAdvertiser: (workspaceId: string, advertiserId: string): Promise<AdAdvertiserDetail> =>
    apiGet<AdAdvertiserDetail>(
      `/api/v1/workspaces/${workspaceId}/ad-library/advertisers/${advertiserId}`,
    ),

  promoteAdvertiser: (
    workspaceId: string,
    advertiserId: string,
    request: AdvertiserPromoteRequest,
  ): Promise<AdvertiserPromoteResult> =>
    apiPost<AdvertiserPromoteResult>(
      `/api/v1/workspaces/${workspaceId}/ad-library/advertisers/${advertiserId}/promote`,
      request,
    ),

  bulkPromote: (
    workspaceId: string,
    request: AdvertiserBulkPromoteRequest,
  ): Promise<AdvertiserBulkPromoteResult> =>
    apiPost<AdvertiserBulkPromoteResult>(
      `/api/v1/workspaces/${workspaceId}/ad-library/advertisers/bulk-promote`,
      request,
    ),

  listMonitors: (workspaceId: string): Promise<AdMonitor[]> =>
    apiGet<AdMonitor[]>(`/api/v1/workspaces/${workspaceId}/ad-library/monitors`),

  createMonitor: (workspaceId: string, request: AdMonitorCreate): Promise<AdMonitor> =>
    apiPost<AdMonitor>(`/api/v1/workspaces/${workspaceId}/ad-library/monitors`, request),

  updateMonitor: (
    workspaceId: string,
    monitorId: string,
    request: AdMonitorUpdate,
  ): Promise<AdMonitor> =>
    apiPatch<AdMonitor>(
      `/api/v1/workspaces/${workspaceId}/ad-library/monitors/${monitorId}`,
      request,
    ),

  deleteMonitor: (workspaceId: string, monitorId: string): Promise<void> =>
    apiDelete(`/api/v1/workspaces/${workspaceId}/ad-library/monitors/${monitorId}`),
};

/** React Query option presets for ad-library reads. */
export const adLibraryQueryOptions = {
  advertisers: (workspaceId: string, params: ListAdvertisersParams = {}) => ({
    queryKey: queryKeys.adLibrary.advertisers(workspaceId, { ...params }),
    queryFn: () => adLibraryApi.listAdvertisers(workspaceId, params),
  }),
  advertiser: (workspaceId: string, advertiserId: string) => ({
    queryKey: queryKeys.adLibrary.advertiser(workspaceId, advertiserId),
    queryFn: () => adLibraryApi.getAdvertiser(workspaceId, advertiserId),
  }),
  monitors: (workspaceId: string) => ({
    queryKey: queryKeys.adLibrary.monitors(workspaceId),
    queryFn: () => adLibraryApi.listMonitors(workspaceId),
  }),
  /** Poll a discovery job while it runs. */
  job: (workspaceId: string, jobId: string) => ({
    queryKey: queryKeys.adLibrary.job(workspaceId, jobId),
    queryFn: () => adLibraryApi.getJob(workspaceId, jobId),
    ...POLL_30S,
  }),
};
