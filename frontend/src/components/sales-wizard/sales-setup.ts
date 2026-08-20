import type { CatalogItemResponse, PricingSettings } from "@/types/sales-wizard";

/**
 * The landscape builder is usable only when a configured package key resolves
 * to an active Price Book row with a real selling price. Tier copy by itself is
 * not setup: the backend drops unresolved rows and produces an empty $0 quote.
 */
export function hasSellableLandscapePackage(
  pricing: PricingSettings | undefined,
  catalog: CatalogItemResponse[] | undefined,
): boolean {
  if (!pricing?.tiers?.length || !catalog?.length) return false;

  const sellableKeys = new Set<string>();
  for (const item of catalog) {
    if (!item.is_active || Number(item.unit_price) <= 0) continue;
    sellableKeys.add(item.id);
    if (item.sku) sellableKeys.add(item.sku);
  }

  return pricing.tiers.some((tier) =>
    tier.sections?.some((section) => section.item_ids?.some((itemId) => sellableKeys.has(itemId))),
  );
}
