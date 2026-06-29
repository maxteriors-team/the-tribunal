// Price book / catalog types. Mirrors the backend `app/schemas/catalog.py`.

export type CatalogItemKind = "service" | "product";

export interface CatalogItem {
  id: string;
  workspace_id: string;
  name: string;
  description?: string | null;
  sku?: string | null;
  kind: CatalogItemKind;
  unit_price: number;
  taxable: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface CreateCatalogItemRequest {
  name: string;
  description?: string;
  sku?: string;
  kind?: CatalogItemKind;
  unit_price?: number;
  taxable?: boolean;
  is_active?: boolean;
}

export interface UpdateCatalogItemRequest {
  name?: string;
  description?: string;
  sku?: string;
  kind?: CatalogItemKind;
  unit_price?: number;
  taxable?: boolean;
  is_active?: boolean;
}
