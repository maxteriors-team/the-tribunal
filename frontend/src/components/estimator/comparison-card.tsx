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

// One seasonal Good/Better/Best package as the client compares it. Feet-free by
// construction: it carries the tier copy and a single ``total`` only, never the
// roofline breakdown, matching the public payload's privacy contract.
export interface ComparisonPackageView {
  key: string;
  name: string;
  marker?: string | null;
  total: number;
  valueTag?: string | null;
  popular?: boolean;
  recommended?: boolean;
  points?: string[];
  experience?: string | null;
}

export interface ComparisonView {
  currency?: string;
  clientName?: string | null;
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
  // Permanent is the upsell whenever it wins over the horizon.
  const permanentWins = bothOffered && view.multi_year_savings > 0;
  const savings = Math.abs(view.multi_year_savings);
  const greeting = view.clientName ? `Prepared for ${view.clientName}` : null;
  const packages = view.christmasPackages ?? [];
  const roofline = view.roofline ?? null;
  // Permanent wins the roofline-only comparison when paying every season costs
  // more over the horizon than installing once.
  const rooflineSavings = roofline && roofline.savings > 0 ? roofline.savings : 0;

  return (
    <div className="cmp-wrap">
      <div className="cmp-head">
        {greeting ? <div className="cmp-brand">{greeting}</div> : null}
        <h1>Permanent vs. Seasonal Lighting</h1>
        <p>
          Two ways to light your home for the holidays — here&apos;s what each
          costs and how they compare over time.
        </p>
      </div>

      {bothOffered && savings > 0 ? (
        <div className="cmp-savings">
          <div className="cmp-savings-label">
            {permanentWins ? "Your savings with permanent" : "Cost difference"}
          </div>
          <div className="cmp-savings-amount">
            {formatCurrency(savings, currency)}
          </div>
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

      <div className="cmp-cards">
        <div className={`cmp-card${permanentWins ? " recommended" : ""}`}>
          {permanentWins ? (
            <span className="cmp-card-tag">Best value over time</span>
          ) : null}
          <h2>Permanent Lighting</h2>
          <div className="cmp-card-kind">One-time install</div>
          {view.permanent.enabled ? (
            <>
              <div className="cmp-price">
                {formatCurrency(view.permanent.total, currency)}
              </div>
              <div className="cmp-price-note">Paid once — yours for years</div>
            </>
          ) : (
            <p className="cmp-unavailable">Not offered in your area yet.</p>
          )}
          <Perks perks={view.permanent_perks} />
        </div>

        <div className="cmp-card">
          <h2>Seasonal Lighting</h2>
          <div className="cmp-card-kind">Per season</div>
          {view.christmas.enabled ? (
            <>
              {view.christmasName ? (
                <div className="cmp-card-pkg">{view.christmasName}</div>
              ) : null}
              <div className="cmp-price">
                {formatCurrency(view.christmas.total, currency)}
              </div>
              <div className="cmp-price-note">
                Every season · {formatCurrency(view.temporary_multi_year, currency)} over{" "}
                {view.years} years
              </div>
            </>
          ) : (
            <p className="cmp-unavailable">Not offered in your area yet.</p>
          )}
          <Perks perks={view.christmas_perks} />
        </div>
      </div>

      {roofline ? (
        <div className="cmp-pkg-section">
          <div className="cmp-pkg-head">
            <h2>Roofline, side by side</h2>
            <p>
              The same run of roofline lights, priced both ways — decor left out
              on purpose, so you&apos;re comparing like for like.
            </p>
          </div>
          <div className="cmp-cards">
            <div
              className={`cmp-card${rooflineSavings > 0 ? " recommended" : ""}`}
            >
              {rooflineSavings > 0 ? (
                <span className="cmp-card-tag">
                  Saves {formatCurrency(rooflineSavings, currency)}
                </span>
              ) : null}
              <h2>Permanent roofline</h2>
              <div className="cmp-card-kind">One-time install</div>
              <div className="cmp-price">
                {formatCurrency(roofline.permanent_total, currency)}
              </div>
              <div className="cmp-price-note">
                Paid once — lit every holiday after that
              </div>
            </div>

            <div className="cmp-card">
              <h2>Seasonal roofline</h2>
              <div className="cmp-card-kind">Per season</div>
              <div className="cmp-price">
                {formatCurrency(roofline.seasonal_total, currency)}
              </div>
              <div className="cmp-price-note">
                Every season ·{" "}
                {formatCurrency(roofline.seasonal_multi_year, currency)} over{" "}
                {view.years} seasons
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {packages.length > 0 ? (
        <div className="cmp-pkg-section">
          <div className="cmp-pkg-head">
            <h2>Choose your seasonal package</h2>
            <p>
              Three ways to light up the season. Pick the look that fits your
              home.
            </p>
          </div>
          <div className="cmp-pkg-grid">
            {packages.map((pkg) => (
              <div
                className={`cmp-card cmp-pkg${pkg.recommended ? " recommended" : ""}`}
                key={pkg.key}
              >
                {pkg.recommended ? (
                  <span className="cmp-card-tag">Recommended</span>
                ) : pkg.popular ? (
                  <span className="cmp-card-tag alt">Most popular</span>
                ) : null}
                <h3>
                  {pkg.marker ? (
                    <span className="cmp-pkg-marker">{pkg.marker}</span>
                  ) : null}
                  {pkg.name}
                </h3>
                {pkg.experience ? (
                  <div className="cmp-pkg-exp">{pkg.experience}</div>
                ) : null}
                <div className="cmp-price">
                  {formatCurrency(pkg.total, currency)}
                </div>
                <div className="cmp-price-note">Per season</div>
                {pkg.points && pkg.points.length > 0 ? (
                  <ul className="cmp-perks">
                    {pkg.points.map((point) => (
                      <li key={point}>{point}</li>
                    ))}
                  </ul>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
