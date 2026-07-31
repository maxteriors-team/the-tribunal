// Seasonal (Christmas) Good/Better/Best package helpers for the roofline
// estimator. The server returns priced packages in `package_order` (most
// inclusive last) on the estimate result; these helpers pick which one the rep
// is selling and how to label it, matching the backend's fallback so the rep
// preview always agrees with the shared public page.
import type { ChristmasPackagePricing } from "@/types/estimate";

/**
 * Resolve the rep's selected seasonal package: their explicit pick when it names
 * a priced package, else the most-inclusive one (last in server `package_order`).
 * Returns `null` when the workspace isn't selling packages (empty list).
 *
 * The server's `_resolve_recommended_package` has one extra step between those
 * two — an operator-flagged `recommended` tier, so a non-seasonal ladder can
 * anchor on its middle option. Seasonal packages carry no such flag (there is no
 * field for it on `ChristmasPackagePricing`), so the two resolvers agree here and
 * the rep preview always matches the shared public page.
 */
export function resolveSelectedPackage(
  packages: ChristmasPackagePricing[],
  selectedKey: string | null | undefined,
): ChristmasPackagePricing | null {
  if (packages.length === 0) return null;
  if (selectedKey) {
    const picked = packages.find((pkg) => pkg.key === selectedKey);
    if (picked) return picked;
  }
  return packages[packages.length - 1] ?? null;
}

/** Client-facing package name, falling back to the internal label. */
export function packageName(pkg: ChristmasPackagePricing): string {
  return pkg.name ?? pkg.label;
}
