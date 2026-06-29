import type {
  CatalogItem,
  CreateCatalogItemRequest,
  UpdateCatalogItemRequest,
} from "@/types";

import { createApiClient } from "./create-api-client";

// Workspace-scoped CRUD from the factory (list/get/create/update/delete). The
// factory's typed overload marks the optional methods nullable; re-expose them
// as required, matching `quotesApi`.
const baseCatalogApi = createApiClient<
  CatalogItem,
  CreateCatalogItemRequest,
  UpdateCatalogItemRequest
>({
  resourcePath: "catalog-items",
});

export const catalogApi = {
  list: baseCatalogApi.list,
  get: baseCatalogApi.get!,
  create: baseCatalogApi.create!,
  update: baseCatalogApi.update!,
  delete: baseCatalogApi.delete!,
};
