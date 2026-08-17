import { landscapeWireLabel } from "@/lib/estimator/fixtures";
import type { CatalogItemResponse } from "@/types/sales-wizard";

export type SupplierCsvCategory = "fixture" | "transformer" | "wire";

export interface SupplierFixtureInput {
  label: string;
  quantity: number;
  item: CatalogItemResponse | null;
  category?: Exclude<SupplierCsvCategory, "wire">;
}

export interface SupplierWireInput {
  label: string;
  wireGauge: 8 | 10 | 12 | 14;
  lengthFeet: number | null;
  item?: CatalogItemResponse | null;
}

export interface SupplierCsvRow {
  category: SupplierCsvCategory;
  catalogItemId: string | null;
  supplier: string;
  manufacturer: string;
  sku: string;
  description: string;
  quantity: number;
  unit: "each" | "ft";
  planSource: string;
  status: "Ready" | "Needs SKU" | "Needs route scale";
  notes: string;
  needed?: number;
  ordered?: number;
  received?: number;
  unitCost?: number | null;
  totalCost?: number | null;
}

function attributeText(attributes: CatalogItemResponse["attributes"], key: string): string {
  const value = attributes?.[key];
  return typeof value === "string" ? value.trim() : "";
}

function roundQuantity(value: number): number {
  return Math.round((value + Number.EPSILON) * 100) / 100;
}

export function buildSupplierCsvRows(
  fixtures: SupplierFixtureInput[],
  wires: SupplierWireInput[],
): SupplierCsvRow[] {
  const rows: SupplierCsvRow[] = [];

  for (const fixture of fixtures) {
    if (fixture.quantity <= 0) continue;
    const item = fixture.item;
    const supplier = attributeText(item?.attributes ?? null, "supplier");
    const manufacturer = attributeText(item?.attributes ?? null, "manufacturer");
    const components = item?.components?.length
      ? item.components
      : [
          {
            sku: item?.sku ?? null,
            description: item?.name ?? fixture.label,
            qty: 1,
          },
        ];

    for (const component of components) {
      const sku = component.sku?.trim() ?? "";
      rows.push({
        category: fixture.category ?? "fixture",
        catalogItemId: item?.id ?? null,
        supplier,
        manufacturer,
        sku,
        description: component.description?.trim() || item?.name || fixture.label,
        quantity: roundQuantity(fixture.quantity * component.qty),
        unit: "each",
        planSource: fixture.label,
        status: sku ? "Ready" : "Needs SKU",
        notes: sku ? "" : "Assign a supplier SKU in the Tribunal catalog before ordering.",
        needed: roundQuantity(fixture.quantity * component.qty),
        ordered: 0,
        received: 0,
        unitCost: item?.unit_price ?? null,
        totalCost: item ? roundQuantity(item.unit_price * fixture.quantity * component.qty) : null,
      });
    }
  }

  for (const wire of wires) {
    const item = wire.item ?? null;
    const sku = item?.sku?.trim() ?? "";
    rows.push({
      category: "wire",
      catalogItemId: item?.id ?? null,
      supplier: attributeText(item?.attributes ?? null, "supplier"),
      manufacturer: attributeText(item?.attributes ?? null, "manufacturer"),
      sku,
      description: item?.name ?? `${landscapeWireLabel(wire.wireGauge)} low-voltage landscape wire`,
      quantity: wire.lengthFeet === null ? 0 : Math.ceil(wire.lengthFeet),
      unit: "ft",
      planSource: wire.label,
      status: wire.lengthFeet === null ? "Needs route scale" : sku ? "Ready" : "Needs SKU",
      needed: wire.lengthFeet === null ? 0 : Math.ceil(wire.lengthFeet),
      ordered: 0,
      received: 0,
      unitCost: item?.unit_price ?? null,
      totalCost:
        item && wire.lengthFeet !== null
          ? roundQuantity(item.unit_price * Math.ceil(wire.lengthFeet))
          : null,
      notes:
        wire.lengthFeet === null
          ? "Set the drawing scale before ordering wire."
          : sku
            ? "Traced one-way route rounded up to a whole foot; add field allowance before ordering."
            : "Assign a supplier SKU in the Tribunal catalog before ordering. Traced route is rounded to a whole foot; add field allowance before ordering.",
    });
  }

  const grouped = new Map<string, SupplierCsvRow>();
  for (const row of rows) {
    const key = [
      row.category,
      row.catalogItemId ?? "",
      row.supplier,
      row.manufacturer,
      row.sku,
      row.description,
      row.unit,
      row.status,
      row.notes,
    ].join("\u0000");
    const existing = grouped.get(key);
    if (!existing) {
      grouped.set(key, { ...row });
      continue;
    }
    existing.quantity = roundQuantity(existing.quantity + row.quantity);
    const sources = new Set(
      `${existing.planSource},${row.planSource}`
        .split(",")
        .map((value) => value.trim())
        .filter(Boolean),
    );
    existing.planSource = [...sources].join(", ");
  }

  return [...grouped.values()].sort((left, right) => {
    const readiness = left.status.localeCompare(right.status);
    if (readiness !== 0) return readiness;
    return left.description.localeCompare(right.description);
  });
}

const CSV_HEADERS = [
  "Supplier",
  "Manufacturer",
  "SKU",
  "Description",
  "Quantity",
  "Unit",
  "Plan source",
  "Status",
  "Needed",
  "Ordered",
  "Received",
  "Unit cost",
  "Total cost",
  "Notes",
] as const;

function spreadsheetSafe(value: string): string {
  return /^[\s]*[=+\-@]/.test(value) ? `'${value}` : value;
}

function csvCell(value: string | number): string {
  const safe = spreadsheetSafe(String(value));
  return `"${safe.replaceAll('"', '""')}"`;
}

export function serializeSupplierCsv(rows: SupplierCsvRow[]): string {
  const body = rows.map((row) =>
    [
      row.supplier,
      row.manufacturer,
      row.sku,
      row.description,
      row.quantity,
      row.unit,
      row.planSource,
      row.status,
      row.needed ?? row.quantity,
      row.ordered ?? 0,
      row.received ?? 0,
      row.unitCost ?? "",
      row.totalCost ?? "",
      row.notes,
    ]
      .map(csvCell)
      .join(","),
  );
  return [CSV_HEADERS.map(csvCell).join(","), ...body].join("\r\n");
}

function safeFilename(value: string): string {
  const normalized = value
    .normalize("NFKD")
    .replace(/[^a-zA-Z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .toLowerCase();
  return normalized || "landscape-lighting-project";
}

export function downloadSupplierCsv(rows: SupplierCsvRow[], projectName: string): void {
  const blob = new Blob(["\uFEFF", serializeSupplierCsv(rows)], {
    type: "text/csv;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${safeFilename(projectName)}-supplier-order.csv`;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
