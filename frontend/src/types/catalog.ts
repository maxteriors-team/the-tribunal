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
  /** Service line this item belongs to; null until an operator classifies it. */
  service_category?: string | null;
  /** True for add-ons sold alongside a primary job (attach-rate numerator). */
  is_attachable: boolean;
  /** Categories this add-on can ride along with, e.g. ["roof"] for gutters. */
  attach_targets: string[];
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
  service_category?: string | null;
  is_attachable?: boolean;
  attach_targets?: string[];
}

export interface UpdateCatalogItemRequest {
  name?: string;
  description?: string;
  sku?: string;
  kind?: CatalogItemKind;
  unit_price?: number;
  taxable?: boolean;
  is_active?: boolean;
  /** Send an explicit `null` to uncategorize an item. */
  service_category?: string | null;
  is_attachable?: boolean;
  attach_targets?: string[];
}
