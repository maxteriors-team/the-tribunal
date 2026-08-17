import type { DesignerShot } from "@/components/estimator/proposal-host";
import type { Product } from "@/lib/estimator/types";
import type { CatalogItemResponse } from "@/types/sales-wizard";

import { recountLandscapeFixtures } from "./landscape-sheets";

export interface LandscapeScheduleRow {
  number: number;
  shotId: string;
  itemId: string;
  productId: string;
  sheetLabel: string;
  fixtureType: string;
  fixtureName: string;
  fixtureCatalogItemId: string | null;
  fixtureSku: string | null;
  lampCatalogItemId: string | null;
  lampName: string | null;
  accessoryCatalogItemIds: string[];
  accessoryNames: string[];
  unresolved: string[];
}

const activeCatalogIndexes = (catalog: readonly CatalogItemResponse[]) => {
  const active = catalog.filter((item) => item.is_active);
  return {
    byId: new Map(active.map((item) => [item.id, item])),
    bySku: new Map(
      active.flatMap((item) => (item.sku?.trim() ? [[item.sku.trim(), item] as const] : [])),
    ),
  };
};

export function buildLandscapeSchedule(
  shots: readonly DesignerShot[],
  products: readonly Product[],
  catalog: readonly CatalogItemResponse[],
): LandscapeScheduleRow[] {
  const productsById = new Map(products.map((product) => [product.id, product]));
  const catalogIndexes = activeCatalogIndexes(catalog);
  const shotsById = new Map(shots.map((shot) => [shot.id, shot]));
  const numbered = recountLandscapeFixtures(shots, (productId) => {
    const product = productsById.get(productId);
    return Boolean(product?.target.field === "landscape");
  });
  const items = new Map(
    shots.flatMap((shot) =>
      shot.design.items.map((item) => [`${shot.id}:${item.id}`, item] as const),
    ),
  );
  return numbered.map((entry) => {
    const item = items.get(`${entry.shotId}:${entry.itemId}`)!;
    const product = productsById.get(entry.productId);
    const fixtureCatalogItemId = item.catalogItemId ?? product?.catalogItemId;
    const fixtureCatalogSku = item.catalogSku ?? product?.catalogSku;
    const fixture =
      (fixtureCatalogItemId ? catalogIndexes.byId.get(fixtureCatalogItemId) : undefined) ??
      (fixtureCatalogSku ? catalogIndexes.bySku.get(fixtureCatalogSku) : undefined) ??
      (product?.sku ? catalogIndexes.byId.get(product.sku) : undefined) ??
      (product?.sku ? catalogIndexes.bySku.get(product.sku) : undefined);
    const lamp = item.lampCatalogItemId
      ? catalogIndexes.byId.get(item.lampCatalogItemId)
      : undefined;
    const accessories = (item.accessoryCatalogItemIds ?? []).flatMap((id) => {
      const catalogItem = catalogIndexes.byId.get(id);
      return catalogItem ? [catalogItem] : [];
    });
    const unresolved: string[] = [];
    if (item.catalogItemId && !fixture)
      unresolved.push("Fixture catalog item is inactive or missing");
    if (item.lampCatalogItemId && !lamp)
      unresolved.push("Lamp catalog item is inactive or missing");
    if (accessories.length !== (item.accessoryCatalogItemIds?.length ?? 0)) {
      unresolved.push("One or more accessories are inactive or missing");
    }
    if (!item.catalogItemId && !product?.sku) unresolved.push("Fixture has no price-book mapping");
    return {
      ...entry,
      sheetLabel:
        shotsById.get(entry.shotId)?.sheet?.drawingNumber ??
        shotsById.get(entry.shotId)?.sheet?.label ??
        "Drawing sheet",
      fixtureType:
        product?.target.field === "landscape" ? product.target.fixtureType : "unresolved",
      fixtureName: fixture?.name ?? product?.productName ?? product?.name ?? "Unresolved fixture",
      fixtureCatalogItemId: fixture?.id ?? item.catalogItemId ?? null,
      fixtureSku: fixture?.sku ?? item.catalogSku ?? product?.sku ?? null,
      lampCatalogItemId: lamp?.id ?? item.lampCatalogItemId ?? null,
      lampName: lamp?.name ?? product?.lampLabel ?? null,
      accessoryCatalogItemIds: accessories.map((accessory) => accessory.id),
      accessoryNames:
        accessories.length > 0
          ? accessories.map((accessory) => accessory.name)
          : (product?.accessoryLabels ?? []),
      unresolved,
    };
  });
}

export function updateFixtureScheduleSelection(
  shots: readonly DesignerShot[],
  itemId: string,
  update: {
    catalogItemId?: string;
    catalogSku?: string;
    lampCatalogItemId?: string;
    accessoryCatalogItemIds?: string[];
  },
): DesignerShot[] {
  return shots.map((shot) => ({
    ...shot,
    design: {
      ...shot.design,
      items: shot.design.items.map((item) => (item.id === itemId ? { ...item, ...update } : item)),
    },
  }));
}

export function copyScheduleSelectionToType(
  shots: readonly DesignerShot[],
  sourceItemId: string,
): DesignerShot[] {
  const source = shots
    .flatMap((shot) => shot.design.items)
    .find((item) => item.id === sourceItemId);
  if (!source) return [...shots];
  return shots.map((shot) => ({
    ...shot,
    design: {
      ...shot.design,
      items: shot.design.items.map((item) =>
        item.productId === source.productId
          ? {
              ...item,
              catalogItemId: source.catalogItemId,
              catalogSku: source.catalogSku,
              lampCatalogItemId: source.lampCatalogItemId,
              accessoryCatalogItemIds: source.accessoryCatalogItemIds,
            }
          : item,
      ),
    },
  }));
}
