import type { LandscapeScheduleRow } from "@/lib/estimator/landscape-schedule";
import type { SupplierCsvRow } from "@/lib/estimator/supplier-csv";
import type { LandscapeProcurementState } from "@/lib/estimator/types";
import type { CatalogItemResponse } from "@/types/sales-wizard";

export type ProcurementStatus = "unresolved" | "not-ordered" | "partial" | "ordered" | "received";

export type LandscapeProcurementCategory =
  | "fixture"
  | "lamp"
  | "accessory"
  | "component"
  | "wire"
  | "transformer";

export interface LandscapeProcurementSupplement {
  key: string;
  category: "wire" | "transformer";
  catalogItemId: string | null;
  sku: string | null;
  name: string;
  manufacturer: string | null;
  supplier: string | null;
  needed: number;
  unit: "each" | "ft";
  unitCost: number | null;
  planSource: string;
  sourceStatus: SupplierCsvRow["status"];
  supplierNote: string;
}

export interface LandscapeProcurementRow {
  key: string;
  category: LandscapeProcurementCategory;
  catalogItemId: string | null;
  name: string;
  sku: string | null;
  manufacturer: string | null;
  supplier: string | null;
  needed: number;
  ordered: number;
  received: number;
  unit: "each" | "ft";
  unitCost: number | null;
  totalCost: number | null;
  planSource: string;
  supplierNote: string;
  sourceStatus: SupplierCsvRow["status"];
  status: ProcurementStatus;
}

interface CountedLine {
  key: string;
  category: LandscapeProcurementCategory;
  catalogItemId: string | null;
  sku: string | null;
  name: string;
  manufacturer: string | null;
  supplier: string | null;
  needed: number;
  unit: "each" | "ft";
  unitCost: number | null;
  planSources: Set<string>;
  sourceStatus: SupplierCsvRow["status"];
  supplierNote: string;
}

const CATEGORY_ORDER: Record<LandscapeProcurementCategory, number> = {
  fixture: 0,
  lamp: 1,
  accessory: 2,
  component: 3,
  wire: 4,
  transformer: 5,
};

function attribute(item: CatalogItemResponse | null, key: string): string | null {
  const value = item?.attributes?.[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function numericAttribute(item: CatalogItemResponse | null, key: string): number | null {
  const value = item?.attributes?.[key];
  const parsed =
    typeof value === "number" ? value : typeof value === "string" ? Number(value) : NaN;
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
}

function roundQuantity(value: number): number {
  return Math.round((value + Number.EPSILON) * 100) / 100;
}

function isLampComponent(sku: string, description: string): boolean {
  return /(^|\b)(lamp|bulb|mr\d{2}|led)(\b|$)/i.test(`${sku} ${description}`);
}

function statusFor(
  resolved: boolean,
  needed: number,
  ordered: number,
  received: number,
): ProcurementStatus {
  if (!resolved) return "unresolved";
  if (received >= needed) return "received";
  if (received > 0 || (ordered > 0 && ordered < needed)) return "partial";
  if (ordered >= needed) return "ordered";
  return "not-ordered";
}

function mergeCountedLine(target: Map<string, CountedLine>, line: CountedLine): void {
  const existing = target.get(line.key);
  if (!existing) {
    target.set(line.key, line);
    return;
  }
  existing.needed = roundQuantity(existing.needed + line.needed);
  for (const source of line.planSources) existing.planSources.add(source);
}

function catalogLine(
  key: string,
  category: LandscapeProcurementCategory,
  item: CatalogItemResponse | null,
  fallbackName: string,
  needed: number,
  planSource: string,
): CountedLine {
  const sku = item?.sku?.trim() || null;
  return {
    key,
    category,
    catalogItemId: item?.id ?? null,
    sku,
    name: item?.name?.trim() || fallbackName,
    manufacturer: attribute(item, "manufacturer"),
    supplier: attribute(item, "supplier"),
    needed: roundQuantity(needed),
    unit: "each",
    unitCost: numericAttribute(item, "unit_cost") ?? item?.unit_price ?? null,
    planSources: new Set([planSource]),
    sourceStatus: sku ? "Ready" : "Needs SKU",
    supplierNote: sku ? "" : "Assign a supplier SKU in the Tribunal catalog before ordering.",
  };
}

function editedValue<T>(value: T | undefined, fallback: T): T {
  return value === undefined ? fallback : value;
}

export function procurementSupplementFromSupplierRow(
  row: SupplierCsvRow,
): LandscapeProcurementSupplement | null {
  if (row.category !== "wire" && row.category !== "transformer") return null;
  const identity = row.catalogItemId ?? (row.sku || row.description);
  return {
    key: `${row.category}:${identity}`,
    category: row.category,
    catalogItemId: row.catalogItemId,
    sku: row.sku || null,
    name: row.description,
    manufacturer: row.manufacturer || null,
    supplier: row.supplier || null,
    needed: row.needed ?? row.quantity,
    unit: row.unit,
    unitCost: row.unitCost ?? null,
    planSource: row.planSource,
    sourceStatus: row.status,
    supplierNote: row.notes,
  };
}

export function buildLandscapeProcurement(
  schedule: readonly LandscapeScheduleRow[],
  catalog: readonly CatalogItemResponse[],
  saved: Readonly<Record<string, LandscapeProcurementState>> = {},
  supplements: readonly LandscapeProcurementSupplement[] = [],
): LandscapeProcurementRow[] {
  const activeCatalog = catalog.filter((item) => item.is_active);
  const catalogById = new Map(activeCatalog.map((item) => [item.id, item]));
  const catalogBySku = new Map(
    activeCatalog.flatMap((item) => (item.sku?.trim() ? [[item.sku.trim(), item] as const] : [])),
  );
  const counted = new Map<string, CountedLine>();

  for (const row of schedule) {
    const fixtureItem =
      (row.fixtureCatalogItemId ? catalogById.get(row.fixtureCatalogItemId) : undefined) ??
      (row.fixtureSku ? catalogBySku.get(row.fixtureSku) : undefined) ??
      null;
    mergeCountedLine(
      counted,
      catalogLine(
        `fixture:${fixtureItem?.id ?? row.fixtureCatalogItemId ?? row.fixtureSku ?? row.itemId}`,
        "fixture",
        fixtureItem,
        row.fixtureName,
        1,
        row.sheetLabel,
      ),
    );

    for (const component of fixtureItem?.components ?? []) {
      const quantity = Math.max(component.qty, 0);
      if (quantity <= 0) continue;
      const componentSku = component.sku?.trim() ?? "";
      if (componentSku && componentSku.toLowerCase() === fixtureItem?.sku?.trim().toLowerCase()) {
        continue;
      }
      const name = component.description?.trim() || componentSku || "Fixture component";
      if (row.lampCatalogItemId && isLampComponent(componentSku, name)) continue;
      const matchedCatalogItem = componentSku ? (catalogBySku.get(componentSku) ?? null) : null;
      mergeCountedLine(
        counted,
        catalogLine(
          `component:${componentSku || name}`,
          "component",
          matchedCatalogItem,
          name,
          quantity,
          row.sheetLabel,
        ),
      );
    }

    if (row.lampCatalogItemId) {
      const lamp = catalogById.get(row.lampCatalogItemId) ?? null;
      mergeCountedLine(
        counted,
        catalogLine(
          `lamp:${lamp?.id ?? row.lampCatalogItemId}`,
          "lamp",
          lamp,
          row.lampName ?? "Lamp",
          1,
          row.sheetLabel,
        ),
      );
    }

    row.accessoryCatalogItemIds.forEach((accessoryId, index) => {
      const accessory = catalogById.get(accessoryId) ?? null;
      const name = row.accessoryNames[index] ?? accessory?.name ?? "Accessory";
      mergeCountedLine(
        counted,
        catalogLine(
          `accessory:${accessory?.id ?? accessoryId}`,
          "accessory",
          accessory,
          name,
          1,
          row.sheetLabel,
        ),
      );
    });
  }

  for (const supplement of supplements) {
    mergeCountedLine(counted, {
      ...supplement,
      planSources: new Set([supplement.planSource]),
    });
  }

  return [...counted.values()]
    .map((line): LandscapeProcurementRow => {
      const edit = saved[line.key];
      const sku = editedValue(edit?.catalogSku, line.sku);
      const needed = editedValue(edit?.neededQuantity, line.needed);
      const ordered = edit?.orderedQuantity ?? 0;
      const received = edit?.receivedQuantity ?? 0;
      const unitCost = editedValue(edit?.unitCost, line.unitCost);
      const sourceStatus =
        line.sourceStatus === "Needs route scale"
          ? line.sourceStatus
          : sku?.trim()
            ? "Ready"
            : "Needs SKU";
      return {
        key: line.key,
        category: line.category,
        catalogItemId: editedValue(edit?.catalogItemId, line.catalogItemId),
        name: editedValue(edit?.description, line.name),
        sku,
        manufacturer: editedValue(edit?.manufacturer, line.manufacturer ?? "") || null,
        supplier: editedValue(edit?.supplier, line.supplier ?? "") || null,
        needed,
        ordered,
        received,
        unit: line.unit,
        unitCost,
        totalCost: unitCost === null ? null : roundQuantity(unitCost * needed),
        planSource: [...line.planSources].sort().join(", "),
        supplierNote: edit?.supplierNote ?? line.supplierNote,
        sourceStatus,
        status: statusFor(sourceStatus === "Ready", needed, ordered, received),
      };
    })
    .sort(
      (a, b) =>
        CATEGORY_ORDER[a.category] - CATEGORY_ORDER[b.category] || a.name.localeCompare(b.name),
    );
}

export function procurementStateForRow(row: LandscapeProcurementRow): LandscapeProcurementState {
  return {
    catalogItemId: row.catalogItemId,
    catalogSku: row.sku,
    description: row.name,
    manufacturer: row.manufacturer ?? "",
    supplier: row.supplier ?? "",
    neededQuantity: Math.max(0, row.needed),
    orderedQuantity: Math.max(0, row.ordered),
    receivedQuantity: Math.max(0, row.received),
    unitCost: row.unitCost,
    supplierNote: row.supplierNote,
  };
}

export function recountLandscapeProcurement(
  saved: Readonly<Record<string, LandscapeProcurementState>>,
): Record<string, LandscapeProcurementState> {
  return Object.fromEntries(
    Object.entries(saved).map(([key, value]) => {
      const resetValue = { ...value };
      delete resetValue.neededQuantity;
      return [key, resetValue];
    }),
  );
}

export function procurementRowsToSupplierCsv(
  rows: readonly LandscapeProcurementRow[],
): SupplierCsvRow[] {
  return rows.map((row) => ({
    category:
      row.category === "wire" ? "wire" : row.category === "transformer" ? "transformer" : "fixture",
    catalogItemId: row.catalogItemId,
    supplier: row.supplier ?? "",
    manufacturer: row.manufacturer ?? "",
    sku: row.sku ?? "",
    description: row.name,
    quantity: row.needed,
    needed: row.needed,
    ordered: row.ordered,
    received: row.received,
    unitCost: row.unitCost,
    totalCost: row.totalCost,
    unit: row.unit,
    planSource: row.planSource,
    status: row.sourceStatus,
    notes: row.supplierNote,
  }));
}

export const procurementTotal = (rows: readonly LandscapeProcurementRow[]): number =>
  rows.reduce((total, row) => total + (row.totalCost ?? 0), 0);
