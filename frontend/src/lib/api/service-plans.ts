import api from "@/lib/api";
import type {
  CreateServicePlanRequest,
  ServicePlan,
  ServicePlanRunResult,
  UpdateServicePlanRequest,
} from "@/types";

import { createApiClient } from "./create-api-client";

// Workspace-scoped CRUD from the factory; the typed overload marks the optional
// methods nullable, so re-expose them as required (matching `catalogApi`).
//
// The resource path stays `recurring-jobs`: only the product surface was renamed
// to Service Plans, and renaming the route would 404 the live app during the
// window where a new frontend is deployed against the older backend.
const baseServicePlansApi = createApiClient<
  ServicePlan,
  CreateServicePlanRequest,
  UpdateServicePlanRequest
>({
  resourcePath: "recurring-jobs",
});

export const servicePlansApi = {
  list: baseServicePlansApi.list,
  get: baseServicePlansApi.get!,
  create: baseServicePlansApi.create!,
  update: baseServicePlansApi.update!,
  delete: baseServicePlansApi.delete!,

  /** Force-generate the next occurrence(s) for a plan now. */
  run: async (
    workspaceId: string,
    planId: string
  ): Promise<ServicePlanRunResult> => {
    const response = await api.post(
      `/api/v1/workspaces/${workspaceId}/recurring-jobs/${planId}/run`
    );
    return response.data as ServicePlanRunResult;
  },
};
