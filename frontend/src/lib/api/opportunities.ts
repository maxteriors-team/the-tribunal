import { apiGet, apiPost, apiPut, apiDelete } from "@/lib/api";
import type {
  Opportunity,
  Pipeline,
  PipelineStage,
} from "@/types";

import { createApiClient } from "./create-api-client";

export interface OpportunitiesListParams {
  page?: number;
  page_size?: number;
  search?: string;
  pipeline_id?: string;
  stage_id?: string;
}

export interface OpportunitiesListResponse {
  items: Opportunity[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface CreateOpportunityRequest {
  name: string;
  description?: string;
  amount?: number;
  currency?: string;
  expected_close_date?: string;
  source?: string;
  pipeline_id: string;
  stage_id?: string;
  primary_contact_id?: number;
}

export interface UpdateOpportunityRequest {
  name?: string;
  description?: string;
  amount?: number;
  currency?: string;
  stage_id?: string;
  expected_close_date?: string;
  assigned_user_id?: string;
  source?: string;
  status?: "open" | "won" | "lost" | "abandoned";
  lost_reason?: string;
  is_active?: boolean;
}

export interface CreatePipelineRequest {
  name: string;
  description?: string;
}

export interface UpdatePipelineRequest {
  name?: string;
  description?: string;
  is_active?: boolean;
}

export interface CreatePipelineStageRequest {
  name: string;
  description?: string;
  order: number;
  probability: number;
  stage_type?: string;
}

export interface UpdatePipelineStageRequest {
  name?: string;
  description?: string;
  order?: number;
  probability?: number;
  stage_type?: string;
}

// Base API client using the factory for opportunity CRUD operations
const baseOpportunitiesApi = createApiClient<
  Opportunity,
  CreateOpportunityRequest,
  UpdateOpportunityRequest
>({
  resourcePath: "opportunities",
});

export const opportunitiesApi = {
  // Pipeline endpoints (custom)
  listPipelines: async (workspaceId: string): Promise<Pipeline[]> => {
    return apiGet<Pipeline[]>(
      `/api/v1/workspaces/${workspaceId}/opportunities/pipelines`
    );
  },

  getPipeline: async (workspaceId: string, pipelineId: string): Promise<Pipeline> => {
    return apiGet<Pipeline>(
      `/api/v1/workspaces/${workspaceId}/opportunities/pipelines/${pipelineId}`
    );
  },

  createPipeline: async (
    workspaceId: string,
    data: CreatePipelineRequest
  ): Promise<Pipeline> => {
    return apiPost<Pipeline>(
      `/api/v1/workspaces/${workspaceId}/opportunities/pipelines`,
      data
    );
  },

  updatePipeline: async (
    workspaceId: string,
    pipelineId: string,
    data: UpdatePipelineRequest
  ): Promise<Pipeline> => {
    return apiPut<Pipeline>(
      `/api/v1/workspaces/${workspaceId}/opportunities/pipelines/${pipelineId}`,
      data
    );
  },

  deletePipeline: async (workspaceId: string, pipelineId: string): Promise<void> => {
    await apiDelete(`/api/v1/workspaces/${workspaceId}/opportunities/pipelines/${pipelineId}`);
  },

  // Pipeline stage endpoints (custom)
  createStage: async (
    workspaceId: string,
    pipelineId: string,
    data: CreatePipelineStageRequest
  ): Promise<PipelineStage> => {
    return apiPost<PipelineStage>(
      `/api/v1/workspaces/${workspaceId}/opportunities/pipelines/${pipelineId}/stages`,
      data
    );
  },

  updateStage: async (
    workspaceId: string,
    pipelineId: string,
    stageId: string,
    data: UpdatePipelineStageRequest
  ): Promise<PipelineStage> => {
    return apiPut<PipelineStage>(
      `/api/v1/workspaces/${workspaceId}/opportunities/pipelines/${pipelineId}/stages/${stageId}`,
      data
    );
  },

  // Opportunity CRUD from factory
  list: baseOpportunitiesApi.list,
  get: baseOpportunitiesApi.get!,
  create: baseOpportunitiesApi.create!,
  update: baseOpportunitiesApi.update!,
  delete: baseOpportunitiesApi.delete!,

  // Line item endpoints (custom)
  addLineItem: async (
    workspaceId: string,
    opportunityId: string,
    data: {
      name: string;
      description?: string;
      quantity: number;
      unit_price: number;
      discount?: number;
    }
  ): Promise<{ id: string; total: number }> => {
    return apiPost<{ id: string; total: number }>(
      `/api/v1/workspaces/${workspaceId}/opportunities/${opportunityId}/line-items`,
      data
    );
  },

  updateLineItem: async (
    workspaceId: string,
    opportunityId: string,
    itemId: string,
    data: {
      name?: string;
      description?: string;
      quantity?: number;
      unit_price?: number;
      discount?: number;
    }
  ): Promise<{ id: string; total: number }> => {
    return apiPut<{ id: string; total: number }>(
      `/api/v1/workspaces/${workspaceId}/opportunities/${opportunityId}/line-items/${itemId}`,
      data
    );
  },

  deleteLineItem: async (
    workspaceId: string,
    opportunityId: string,
    itemId: string
  ): Promise<void> => {
    await apiDelete(
      `/api/v1/workspaces/${workspaceId}/opportunities/${opportunityId}/line-items/${itemId}`
    );
  },

  deleteStage: async (
    workspaceId: string,
    pipelineId: string,
    stageId: string
  ): Promise<void> => {
    await apiDelete(
      `/api/v1/workspaces/${workspaceId}/opportunities/pipelines/${pipelineId}/stages/${stageId}`
    );
  },
};
