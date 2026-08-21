"use client";

/**
 * Client-facing permanent-vs-temporary savings card.
 *
 * Shared by the authenticated rep tool (as a "what the client sees" preview) and
 * the public `/p/compare/[token]` page. It renders ONLY prices, the multi-year
 * savings, and the perks of each option — never linear feet. The props type is
 * deliberately the feet-free intersection of the estimate + public payloads so a
 * measurement value cannot be passed in by construction.
 */
import { formatCurrency } from "@/lib/utils/number";

import { PackageGrid, type ComparisonPackageView, type PackageSectionCopy } from "./package-grid";

// Re-exported so existing importers (and the settings preview) have one place to
// get the client-facing package view from.
export type { ComparisonPackageView, PackageSectionCopy };

export interface ComparisonView {
  currency?: string;
  clientName?: string | null;
  discountAmount?: number;
  permanent: { enabled: boolean; total: number };
  christmas: { enabled: boolean; total: number };
  // Name of the seasonal package the rep selected (Good/Better/Best), shown above
  // the seasonal price. Undefined for à la carte seasonal and on the public page,
  // whose totals-only payload carries no package label — the total already
  // reflects the chosen package server-side.
  christmasName?: string | null;
  difference: number;
  years: number;
  temporary_multi_year: number;
  permanent_one_time: number;
  multi_year_savings: number;
  // Optional to match the generated OpenAPI types: the backend perks lists have
  // server-side defaults, so they surface as `string[] | undefined`.
  permanent_perks?: string[];
  christmas_perks?: string[];
  // Seasonal Good/Better/Best ladder (feet-free totals only). When present, the
  // card renders a package grid under the permanent-vs-seasonal comparison so the
  // client can compare tiers. Empty/undefined => à la carte seasonal pricing.
  christmasPackages?: ComparisonPackageView[];
  // Category copy for that package grid. Omitted for seasonal lighting, which
  // keeps the grid's built-in holiday wording; a non-seasonal category (roof,
  // siding, gutters) passes its own headline and price note so the same grid
  // sells a different trade without a second component.
  packageSection?: PackageSectionCopy | null;
  // Roofline-only, like-for-like cost comparison: permanent's one-time roofline
  // install against the seasonal roofline paid each season. The headline totals
  // can include decor, which makes them apples-to-oranges; this block is the
  // honest version. Present only when the workspace turns the comparison on and
  // both sides are offered — null/undefined renders nothing. Costs only, no feet.
  roofline?: {
    permanent_total: number;
    seasonal_total: number;
    seasonal_multi_year: number;
    savings: number;
  } | null;
  // Standalone add-ons the rep put on this estimate. Already inside the totals
  // above and listed separately here, because a price that moved with no line
  // to explain it is the fastest way to lose a signature. Empty => nothing extra.
  //
  // `packageKey` names the tier a line was priced *inside* (rather than on top
  // of every tier), so the reason it appears and disappears with the package is
  // on the page instead of left to the client to guess. Undefined/null => the
  // line rides on whichever tier they pick, which is the default.
  customLines?: {
    label: string;
    description?: string | null;
    quantity?: number;
    amount: number;
    side?: "permanent" | "seasonal";
    packageKey?: string | null;
  }[];
}

/**
 * The tier a scoped add-on was priced inside, by name — or null when the line
 * rides on every tier (the default) or names a package this ladder doesn't show.
 * Never the raw package key — an internal identifier, not client copy.
 */
function packageNameFor(
  packageKey: string | null | undefined,
  packages: ComparisonPackageView[],
): string | null {
  if (!packageKey) return null;
  return packages.find((pkg) => pkg.key === packageKey)?.name ?? null;
}

function Perks({ perks }: { perks?: string[] }) {
  const items = perks ?? [];
  if (items.length === 0) return null;
  return (
    <ul className="cmp-perks">
      {items.map((perk) => (
        <li key={perk}>{perk}</li>
      ))}
    </ul>
  );
}

export function ComparisonCard({ view }: { view: ComparisonView }) {
  const currency = view.currency || "USD";
  const bothOffered = view.permanent.enabled && view.christmas.enabled;
  const permanentOnly = view.permanent.enabled && !view.christmas.enabled;
  const seasonalOnly = view.christmas.enabled && !view.permanent.enabled;
  // Permanent is the upsell whenever it wins over the horizon.
  const permanentWins = bothOffered && view.multi_year_savings > 0;
  const savings = Math.abs(view.multi_year_savings);
  const greeting = view.clientName ? `Prepared for ${view.clientName}` : null;
  const packages = view.christmas.enabled ? (view.christmasPackages ?? []) : [];
  const roofline = bothOffered ? (view.roofline ?? null) : null;
  const customLines = view.customLines ?? [];
  const heading = permanentOnly
    ? "Permanent Lighting Proposal"
    : seasonalOnly
      ? "Seasonal Lighting Proposal"
      : "Permanent vs. Seasonal Lighting";
  const intro = permanentOnly
    ? "A permanent lighting package designed for your home — installed once and ready year-round."
    : seasonalOnly
      ? "A seasonal lighting package designed for your home and this year’s display."
      : "Two ways to light your home for the holidays — here’s what each costs and how they compare over time.";
  // Permanent wins the roofline-only comparison when paying every season costs
  // more over the horizon than installing once.
  const rooflineSavings = roofline && roofline.savings > 0 ? roofline.savings : 0;

  return (
    <div className="cmp-wrap">
      <div className="cmp-head">
        {greeting ? <div className="cmp-brand">{greeting}</div> : null}
        <h1>{heading}</h1>
        <p>{intro}</p>
      </div>

      {(view.discountAmount ?? 0) > 0 ? (
        <div className="cmp-discount" role="status">
          <span>Proposal discount applied</span>
          <strong>−{formatCurrency(view.discountAmount ?? 0, currency)}</strong>
        </div>
      ) : null}

      {bothOffered && savings > 0 ? (
        <div className="cmp-savings">
          <div className="cmp-savings-label">
            {permanentWins ? "Your savings with permanent" : "Cost difference"}
          </div>
          <div className="cmp-savings-amount">{formatCurrency(savings, currency)}</div>
          <div className="cmp-savings-sub">
            {permanentWins
              ? `Over ${view.years} seasons, permanent lighting saves you ${formatCurrency(
                  savings,
                  currency,
                )} versus paying for seasonal install every year (${formatCurrency(
                  view.temporary_multi_year,
                  currency,
                )} total).`
              : `Estimated difference over ${view.years} seasons of seasonal installs (${formatCurrency(
                  view.temporary_multi_year,
                  currency,
                )} total) versus permanent's one-time ${formatCurrency(
                  view.permanent_one_time,
                  currency,
                )}.`}
          </div>
        </div>
      ) : null}

      <div className={`cmp-cards${bothOffered ? "" : " single"}`}>
        {view.permanent.enabled ? (
          <div className={`cmp-card${permanentWins ? " recommended" : ""}`}>
            {permanentWins ? <span className="cmp-card-tag">Best value over time</span> : null}
            <h2>Permanent Lighting</h2>
            <div className="cmp-card-kind">One-time install</div>
            <div className="cmp-price">{formatCurrency(view.permanent.total, currency)}</div>
            <div className="cmp-price-note">Paid once — yours for years</div>
            <Perks perks={view.permanent_perks} />
          </div>
        ) : null}

        {view.christmas.enabled ? (
          <div className="cmp-card">
            <h2>Seasonal Lighting</h2>
            <div className="cmp-card-kind">Per season</div>
            {view.christmasName ? <div className="cmp-card-pkg">{view.christmasName}</div> : null}
            <div className="cmp-price">{formatCurrency(view.christmas.total, currency)}</div>
            <div className="cmp-price-note">
              Every season · {formatCurrency(view.temporary_multi_year, currency)} over {view.years}{" "}
              years
            </div>
            <Perks perks={view.christmas_perks} />
          </div>
        ) : null}
      </div>

      {roofline ? (
        <div className="cmp-pkg-section">
          <div className="cmp-pkg-head">
            <h2>Roofline, side by side</h2>
            <p>
              The same run of roofline lights, priced both ways — decor left out on purpose, so
              you&apos;re comparing like for like.
            </p>
          </div>
          <div className="cmp-cards">
            <div className={`cmp-card${rooflineSavings > 0 ? " recommended" : ""}`}>
              {rooflineSavings > 0 ? (
                <span className="cmp-card-tag">
                  Saves {formatCurrency(rooflineSavings, currency)}
                </span>
              ) : null}
              <h2>Permanent roofline</h2>
              <div className="cmp-card-kind">One-time install</div>
              <div className="cmp-price">{formatCurrency(roofline.permanent_total, currency)}</div>
              <div className="cmp-price-note">Paid once — lit every holiday after that</div>
            </div>

            <div className="cmp-card">
              <h2>Seasonal roofline</h2>
              <div className="cmp-card-kind">Per season</div>
              <div className="cmp-price">{formatCurrency(roofline.seasonal_total, currency)}</div>
              <div className="cmp-price-note">
                Every season · {formatCurrency(roofline.seasonal_multi_year, currency)} over{" "}
                {view.years} seasons
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {customLines.length > 0 ? (
        <div className="cmp-pkg-section">
          <div className="cmp-pkg-head">
            <h2>Also included in your price</h2>
            <p>Work we added for your home specifically — already counted in the totals above.</p>
          </div>
          <div className="cmp-addons">
            {customLines.map((line, i) => (
              <div className="cmp-addon" key={`${line.label}-${i}`}>
                <span className="cmp-addon-name">
                  {line.quantity && line.quantity !== 1
                    ? `${line.quantity} × ${line.label}`
                    : line.label}
                  {line.description ? (
                    <span className="cmp-addon-note">{line.description}</span>
                  ) : null}
                  {packageNameFor(line.packageKey, packages) ? (
                    <span className="cmp-addon-note">
                      Included with {packageNameFor(line.packageKey, packages)}
                    </span>
                  ) : null}
                </span>
                <span className="cmp-addon-amount">
                  {formatCurrency(line.amount, currency)}
                  {line.side === "seasonal" ? (
                    <span className="cmp-addon-per">per season</span>
                  ) : (
                    <span className="cmp-addon-per">one-time</span>
                  )}
                </span>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <PackageGrid packages={packages} currency={currency} copy={view.packageSection} />
    </div>
  );
}
