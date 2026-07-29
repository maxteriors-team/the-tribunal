"use client";

/**
 * The client-facing good/better/best package grid — for any service category.
 *
 * Extracted verbatim from `ComparisonCard` so the same three cards, the same
 * "Recommended" / "Most popular" badges, and the same steered-middle highlight
 * that seasonal lighting has always used can also present a roof, siding, or
 * gutter ladder. Nothing about the seasonal rendering changed: every prop below
 * defaults to the copy that card shipped with, so a caller that passes only
 * packages produces byte-identical markup.
 *
 * Feet-free by construction, exactly like the payload it renders: a card carries
 * tier copy and a single `total`, never the measurement or the pricing
 * breakdown that produced it.
 */
import { formatCurrency } from "@/lib/utils/number";

// One package as the client compares it. Feet-free by construction: it carries
// the tier copy and a single ``total`` only, never the pricing breakdown,
// matching the public payload's privacy contract.
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

/**
 * Category-specific copy for the grid. Every field is optional and falls back to
 * the seasonal wording the card has always rendered, so this is additive: a
 * roofing category supplies its own headline, a Christmas one supplies nothing.
 */
export interface PackageSectionCopy {
  title?: string | null;
  blurb?: string | null;
  /** The small note under each price ("Per season", "One-time install", …). */
  priceNote?: string | null;
}

const DEFAULT_TITLE = "Choose your seasonal package";
const DEFAULT_BLURB =
  "Three ways to light up the season. Pick the look that fits your home.";
const DEFAULT_PRICE_NOTE = "Per season";

interface PackageGridProps {
  packages: ComparisonPackageView[];
  currency?: string;
  copy?: PackageSectionCopy | null;
}

export function PackageGrid({ packages, currency, copy }: PackageGridProps) {
  if (packages.length === 0) return null;

  const money = currency || "USD";
  const title = copy?.title || DEFAULT_TITLE;
  const blurb = copy?.blurb || DEFAULT_BLURB;
  const priceNote = copy?.priceNote || DEFAULT_PRICE_NOTE;

  return (
    <div className="cmp-pkg-section">
      <div className="cmp-pkg-head">
        <h2>{title}</h2>
        <p>{blurb}</p>
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
            <div className="cmp-price">{formatCurrency(pkg.total, money)}</div>
            <div className="cmp-price-note">{priceNote}</div>
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
  );
}
