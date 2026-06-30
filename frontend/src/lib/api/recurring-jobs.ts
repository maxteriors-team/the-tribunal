import api from "@/lib/api";
import type {
  CreateRecurringJobRequest,
  RecurringJobRunResult,
  RecurringJobTemplate,
  UpdateRecurringJobRequest,
} from "@/types";

import { createApiClient } from "./create-api-client";

// Workspace-scoped CRUD from the factory; the typed overload marks the optional
// methods nullable, so re-expose them as required (matching `catalogApi`).
const baseRecurringJobsApi = createApiClient<
  RecurringJobTemplate,
  CreateRecurringJobRequest,
  UpdateRecurringJobRequest
>({
  resourcePath: "recurring-jobs",
});

export const recurringJobsApi = {
  list: baseRecurringJobsApi.list,
  get: baseRecurringJobsApi.get!,
  create: baseRecurringJobsApi.create!,
  update: baseRecurringJobsApi.update!,
  delete: baseRecurringJobsApi.delete!,

  /** Force-generate the next occurrence(s) for a template now. */
  run: async (
    workspaceId: string,
    templateId: string
  ): Promise<RecurringJobRunResult> => {
    const response = await api.post(
      `/api/v1/workspaces/${workspaceId}/recurring-jobs/${templateId}/run`
    );
    return response.data as RecurringJobRunResult;
  },
};
