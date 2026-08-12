import type { LandscapeProcurementState } from "@/lib/estimator/types";
import type { CatalogItemResponse } from "@/types/sales-wizard";

import type { LandscapeScheduleRow } from "./landscape-schedule";

export type ProcurementStatus = "unresolved" | "not-ordered" | "partial" | "ordered" | "received";

export interface LandscapeProcurementRow {
  key: string;
  category: "fixture" | "lamp" | "accessory" | "component" | "wire" | "transformer";
  catalogItemId: string | null;
  name: string;
  sku: string | null;
  manufacturer: string | null;
  supplier: string | null;
  needed: number;
  ordered: number;
  received: number;
  unitCost: number | null;
  totalCost: number | null;
  supplierNote: string;
  status: ProcurementStatus;
}

const attribute = (item: CatalogItemResponse, key: string): string | null => {
  const value = item.attributes?.[key];
  return typeof value === "string" && value.trim() ? value : null;
};

const statusFor = (
  resolved: boolean,
  needed: number,
  ordered: number,
  received: number,
): ProcurementStatus => {
  if (!resolved) return "unresolved";
  if (received >= needed) return "received";
  if (received > 0 || (ordered > 0 && ordered < needed)) return "partial";
  if (ordered >= needed) return "ordered";
  return "not-ordered";
};

interface CountedCatalogLine {
  key: string;
  category: LandscapeProcurementRow["category"];
  catalogItemId: string | null;
  sku: string | null;
  fallbackName: string;
  needed: number;
}

function countScheduleLines(rows: readonly LandscapeScheduleRow[]): CountedCatalogLine[] {
  const counts = new Map<string, CountedCatalogLine>();
  const add = (
    category: CountedCatalogLine["category"],
    catalogItemId: string | null,
    sku: string | null,
    fallbackName: string,
    quantity = 1,
  ) => {
    const key = `${category}:${catalogItemId ?? sku ?? fallbackName}`;
    const existing = counts.get(key);
    counts.set(key, existing ? { ...existing, needed: existing.needed + quantity } : {
      key,
      category,
      catalogItemId,
      sku,
      fallbackName,
      needed: quantity,
    });
  };
  for (const row of rows) {
    add("fixture", row.fixtureCatalogItemId, row.fixtureSku, row.fixtureName);
    if (row.lampCatalogItemId || row.lampName) {
      add("lamp", row.lampCatalogItemId, null, row.lampName ?? "Unresolved lamp");
    }
    row.accessoryNames.forEach((name, index) =>
      add("accessory", row.accessoryCatalogItemIds[index] ?? null, null, name),
    );
  }
  return [...counts.values()];
}

export function buildLandscapeProcurement(
  schedule: readonly LandscapeScheduleRow[],
  catalog: readonly CatalogItemResponse[],
  state: Readonly<Record<string, LandscapeProcurementState>> = {},
): LandscapeProcurementRow[] {
  const activeById = new Map(catalog.filter((item) => item.is_active).map((item) => [item.id, item]));
  const activeBySku = new Map(
    catalog.filter((item) => item.is_active && item.sku).map((item) => [item.sku!, item]),
  );
  const counted = countScheduleLines(schedule);
  const componentLines: CountedCatalogLine[] = [];
  for (const line of counted) {
    const parent =
      (line.catalogItemId ? activeById.get(line.catalogItemId) : undefined) ??
      (line.sku ? activeBySku.get(line.sku) : undefined);
    for (const component of parent?.components ?? []) {
      componentLines.push({
        key: `component:${component.sku}`,
        category: "component",
        catalogItemId: activeBySku.get(component.sku)?.id ?? null,
        sku: component.sku,
        fallbackName: component.description || component.sku,
        needed: line.needed * component.qty,
      });
    }
  }
  const merged = new Map<string, CountedCatalogLine>();
  for (const line of [...counted, ...componentLines]) {
    const existing = merged.get(line.key);
    merged.set(line.key, existing ? { ...existing, needed: existing.needed + line.needed } : line);
  }
  return [...merged.values()].map((line) => {
    const catalogItem =
      (line.catalogItemId ? activeById.get(line.catalogItemId) : undefined) ??
      (line.sku ? activeBySku.get(line.sku) : undefined);
    const saved = state[line.key];
    const ordered = Math.max(0, saved?.orderedQuantity ?? 0);
    const received = Math.max(0, saved?.receivedQuantity ?? 0);
    return {
      key: line.key,
      category: line.category,
      catalogItemId: catalogItem?.id ?? line.catalogItemId,
      name: catalogItem?.name ?? line.fallbackName,
      sku: catalogItem?.sku ?? line.sku,
      manufacturer: catalogItem ? attribute(catalogItem, "manufacturer") : null,
      supplier: catalogItem ? attribute(catalogItem, "supplier") : null,
      needed: line.needed,
      ordered,
      received,
      unitCost: catalogItem?.unit_price ?? null,
      totalCost: catalogItem ? catalogItem.unit_price * line.needed : null,
      supplierNote: saved?.supplierNote ?? "",
      status: statusFor(Boolean(catalogItem), line.needed, ordered, received),
    };
  });
}

export const procurementTotal = (rows: readonly LandscapeProcurementRow[]): number =>
  rows.reduce((total, row) => total + (row.totalCost ?? 0), 0);
