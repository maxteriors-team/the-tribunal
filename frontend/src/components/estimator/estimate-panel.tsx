"use client";

/**
 * Rep-facing itemized estimate readout (right column).
 *
 * Every figure here is server-authoritative — it comes straight from the
 * `quotes/estimate` response, never computed on the client. It shows the
 * measured roofline (internal-only), per-category seasonal decor costs, headline
 * totals, and a highlighted permanent service price. The client-facing view is
 * the separate `ComparisonCard`.
 *
 * When the workspace sells Christmas as Good/Better/Best packages, the response
 * carries `christmas_packages`; the rep picks one here and the seasonal headline
 * reflects that package's total (matching what the client sees on the share).
 *
 * Standalone line items are edited here too. They are the one thing on this
 * panel the rep types a price for, and by default they sit *outside* the package
 * ladder: switching Good→Best re-prices the package and leaves the add-ons
 * alone. A line can instead be scoped to one tier — the bucket truck Best needs
 * and Good doesn't — and then it is priced inside that card only.
 */
import { Plus, X } from "lucide-react";

import {
  MAX_CUSTOM_LINES,
  newCustomLineDraft,
  type CustomLineDraft,
  type CustomLineSide,
} from "@/lib/estimator/custom-lines";
import { COVERAGE_OPTIONS, formatFeet, type CoverageKey } from "@/lib/estimator/design";
import { packageName, resolveSelectedPackage, seasonalTotal } from "@/lib/estimator/packages";
import { formatCurrency } from "@/lib/utils/number";
import type { ChristmasPackagePricing, LinearFeetEstimateResult } from "@/types/estimate";

/** Which halves of the comparison this workspace actually sells. */
export interface EstimateSides {
  permanent: boolean;
  seasonal: boolean;
}

interface EstimatePanelProps {
  estimate: LinearFeetEstimateResult | null | undefined;
  isFetching: boolean;
  feet: number;
  calibrated: boolean;
  hasDesign: boolean;
  selectedPackage: string | null;
  onSelectPackage: (key: string) => void;
  /** Rep-entered standalone lines, independent of any package. */
  customLines: CustomLineDraft[];
  onChangeCustomLines: (lines: CustomLineDraft[]) => void;
  sides: EstimateSides;
  /**
   * How much of the house is being quoted. Undefined hides the control, for
   * designs with no permanent side to scope.
   */
  coverage?: CoverageKey;
  onSelectCoverage?: (coverage: CoverageKey) => void;
  /** Measured permanent feet each coverage level would price. */
  coverageFeet?: Record<CoverageKey, number>;
  /**
   * Priced permanent total per coverage level, in `COVERAGE_OPTIONS` order.
   * `null` for a level still loading, so a card never shows a stale price.
   */
  coveragePrices?: (number | null)[];
}

export function EstimatePanel({
  estimate,
  isFetching,
  feet,
  calibrated,
  hasDesign,
  selectedPackage,
  onSelectPackage,
  customLines,
  onChangeCustomLines,
  sides,
  coverage,
  onSelectCoverage,
  coverageFeet,
  coveragePrices,
}: EstimatePanelProps) {
  const permanent = estimate?.permanent;
  const christmas = estimate?.christmas;
  const decor = christmas?.items ?? [];

  // Rep controls follow workspace capabilities; customer visibility is filtered upstream.
  const packages = sides.seasonal ? (estimate?.christmas_packages ?? []) : [];
  const hasPackages = packages.length > 0;
  const selectedPkg = resolveSelectedPackage(packages, selectedPackage);
  const seasonalSubtotal = seasonalTotal(
    { total: christmas?.subtotal ?? 0, custom_total: christmas?.custom_total },
    selectedPkg,
  );
  const seasonalHeadline = Math.max(
    0,
    seasonalSubtotal -
      (estimate?.proposal_side === "seasonal" || estimate?.proposal_side === "comparison"
        ? (estimate?.discount_amount ?? 0)
        : 0),
  );
  const permanentTotal = sides.permanent ? (permanent?.total ?? 0) : 0;

  return (
    <div className="ep-panel">
      <div className="ep-title">Estimate</div>

      {!hasDesign ? (
        <p className="ep-empty">
          Pick a product on the left and trace it onto the photo. Pricing updates live as you draw —
          or add a line item below for work that isn’t on the photo.
        </p>
      ) : (
        <>
          {!calibrated ? (
            <p className="ep-warn">
              ⚠ No scale set — lengths assume the photo is 60 ft wide. Use{" "}
              <strong>Set scale</strong> for accurate pricing.
            </p>
          ) : null}

          {feet > 0 ? (
            <div className="ep-metric">
              <span className="ep-metric-value">
                {feet} ft
                <span className="est-internal-badge">Internal only</span>
              </span>
              <span className="ep-metric-label">Measured roofline</span>
            </div>
          ) : null}

          {coverage && onSelectCoverage ? (
            <div className="ep-packages">
              <div className="ep-lines-head">Permanent lighting coverage</div>
              <p className="ep-pkg-hint">
                The client sees all three. Each one adds a face of the house — tag every drawn line
                front, side, or back to change what a level includes.
              </p>
              <div className="ep-pkgs" role="group" aria-label="Permanent lighting coverage">
                {COVERAGE_OPTIONS.map((option, index) => {
                  const isSelected = coverage === option.key;
                  const price = coveragePrices?.[index] ?? null;
                  return (
                    <button
                      type="button"
                      key={option.key}
                      className={`ep-pkg${isSelected ? " selected" : ""}${
                        "popular" in option && option.popular ? " popular" : ""
                      }`}
                      aria-pressed={isSelected}
                      onClick={() => onSelectCoverage(option.key)}
                    >
                      {"popular" in option && option.popular ? (
                        <span className="ep-pkg-pop">Most Popular</span>
                      ) : null}
                      <span className="ep-pkg-marker">{option.marker}</span>
                      <span className="ep-pkg-name">{option.label}</span>
                      {price === null ? null : (
                        <span className="ep-pkg-total">{formatCurrency(price)}</span>
                      )}
                      <span className="ep-pkg-per">
                        One-time · {formatFeet(coverageFeet?.[option.key] ?? 0)}
                      </span>
                      <span className="ep-pkg-blurb">{option.blurb}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          ) : null}

          {hasPackages && !isFetching ? (
            <div className="ep-packages">
              <div className="ep-lines-head">Recommended package</div>
              <p className="ep-pkg-hint">
                The client sees all three. This is the one you&rsquo;re recommending, highlighted on
                their page.
              </p>
              <div className="ep-pkgs">
                {packages.map((pkg) => {
                  const isSelected = selectedPkg?.key === pkg.key;
                  return (
                    <button
                      type="button"
                      key={pkg.key}
                      className={`ep-pkg${isSelected ? " selected" : ""}${
                        pkg.popular ? " popular" : ""
                      }`}
                      aria-pressed={isSelected}
                      onClick={() => onSelectPackage(pkg.key)}
                    >
                      {pkg.popular ? <span className="ep-pkg-pop">Most Popular</span> : null}
                      {pkg.value_tag ? <span className="ep-pkg-tag">{pkg.value_tag}</span> : null}
                      {pkg.marker ? <span className="ep-pkg-marker">{pkg.marker}</span> : null}
                      <span className="ep-pkg-name">{pkg.name ?? pkg.label}</span>
                      <span className="ep-pkg-total">
                        {formatCurrency(
                          Math.max(
                            0,
                            pkg.pricing.total -
                              (estimate?.proposal_side === "seasonal" ||
                              estimate?.proposal_side === "comparison"
                                ? (estimate?.discount_amount ?? 0)
                                : 0),
                          ),
                        )}
                      </span>
                      <span className="ep-pkg-per">Per season</span>
                      {pkg.experience ? (
                        <span className="ep-pkg-blurb">{pkg.experience}</span>
                      ) : null}
                    </button>
                  );
                })}
              </div>
            </div>
          ) : !isFetching && sides.seasonal && decor.length > 0 ? (
            <div className="ep-lines">
              <div className="ep-lines-head">Seasonal add-ons</div>
              {decor.map((line) => (
                <div className="ep-line" key={line.key}>
                  <span className="ep-line-name">{line.label}</span>
                  <span className="ep-line-amount">{formatCurrency(line.cost)}</span>
                </div>
              ))}
            </div>
          ) : null}
        </>
      )}

      <CustomLines
        lines={customLines}
        onChange={onChangeCustomLines}
        sides={sides}
        permanentTotal={permanent?.custom_total ?? 0}
        seasonalTotal={christmas?.custom_total ?? 0}
        packages={packages}
      />

      {hasDesign ? (
        isFetching ? (
          <p className="ep-empty">Pricing…</p>
        ) : (
          <>
            <div className="ep-totals">
              {sides.permanent ? (
                <div className="ep-total-row">
                  <span>Permanent · one-time</span>
                  <span className="ep-total-amount">{formatCurrency(permanentTotal)}</span>
                </div>
              ) : null}
              {sides.seasonal ? (
                <div className="ep-total-row ep-total-grand">
                  <span>Seasonal · per year</span>
                  <span className="ep-total-amount">{formatCurrency(seasonalHeadline)}</span>
                </div>
              ) : null}
            </div>

            {sides.permanent && permanentTotal > 0 ? (
              <div className="ep-savings">
                <span className="ep-savings-label">Service price</span>
                <span className="ep-savings-amount">{formatCurrency(permanentTotal)}</span>
              </div>
            ) : null}
          </>
        )
      ) : null}
    </div>
  );
}

/**
 * The standalone-line editor.
 *
 * Rows are raw text until they're complete, so a half-typed price never reaches
 * the request (see `toEstimateCustomLines`). The subtotals under the rows are
 * the server's, not a client sum — this panel prices nothing.
 */
function CustomLines({
  lines,
  onChange,
  sides,
  permanentTotal,
  seasonalTotal: seasonalCustomTotal,
  packages,
}: {
  lines: CustomLineDraft[];
  onChange: (lines: CustomLineDraft[]) => void;
  sides: EstimateSides;
  permanentTotal: number;
  seasonalTotal: number;
  /** Priced seasonal tiers a line can be scoped to. Empty => no scope picker. */
  packages: ChristmasPackagePricing[];
}) {
  // Nothing to bill against: a workspace that sells neither side has no total
  // for a line item to land on.
  if (!sides.permanent && !sides.seasonal) return null;

  const defaultSide: CustomLineSide = sides.seasonal ? "seasonal" : "permanent";
  const bothSides = sides.permanent && sides.seasonal;
  const atCap = lines.length >= MAX_CUSTOM_LINES;
  const hasPackages = packages.length > 0;

  const patch = (id: string, values: Partial<CustomLineDraft>) =>
    onChange(lines.map((l) => (l.id === id ? { ...l, ...values } : l)));

  return (
    <div className="ep-custom">
      <div className="ep-lines-head">Line items</div>
      <p className="ep-pkg-hint">
        {hasPackages
          ? "Anything that isn’t in the price book. Added on top of whichever package they pick — or put inside one tier."
          : "Anything that isn’t in the price book — a trip charge, a custom install, a credit."}
      </p>

      {lines.map((line) => (
        // Two rows per line: the rail is 280–344px wide, and one row of four
        // controls squeezes the description down to a few characters.
        <div className="ep-custom-row" key={line.id}>
          <div className="ep-custom-top">
            <input
              className="est-input ep-custom-label"
              type="text"
              placeholder="What is it?"
              autoComplete="off"
              value={line.label}
              onChange={(e) => patch(line.id, { label: e.target.value })}
              aria-label="Line item description"
            />
            <button
              type="button"
              className="ep-custom-remove"
              title="Remove this line"
              aria-label={`Remove ${line.label.trim() || "line item"}`}
              onClick={() => onChange(lines.filter((l) => l.id !== line.id))}
            >
              <X aria-hidden="true" />
            </button>
          </div>
          <div className="ep-custom-fields">
            <input
              className="est-input ep-custom-qty"
              type="number"
              min={0}
              step={1}
              inputMode="decimal"
              placeholder="1"
              value={line.quantity}
              onChange={(e) => patch(line.id, { quantity: e.target.value })}
              aria-label="Line item quantity"
            />
            <input
              className="est-input ep-custom-price"
              type="number"
              min={0}
              step={1}
              inputMode="decimal"
              placeholder="$ each"
              value={line.unitPrice}
              onChange={(e) => patch(line.id, { unitPrice: e.target.value })}
              aria-label="Line item price"
            />
            {bothSides ? (
              <select
                className="est-select ep-custom-side"
                value={line.side}
                aria-label="Line item applies to"
                onChange={(e) => patch(line.id, { side: e.target.value as CustomLineSide })}
              >
                <option value="seasonal">Per season</option>
                <option value="permanent">One-time</option>
              </select>
            ) : null}
          </div>
          {/* The ladder is seasonal, so only a per-season line has a card to
              live inside — scoping a one-time line would price it nowhere. */}
          {hasPackages && line.side === "seasonal" ? (
            <select
              className="est-select ep-custom-pkg"
              value={line.packageKey ?? ""}
              aria-label="Line item package"
              onChange={(e) => patch(line.id, { packageKey: e.target.value || null })}
            >
              <option value="">All packages</option>
              {packages.map((pkg) => (
                <option key={pkg.key} value={pkg.key}>
                  Only {packageName(pkg)}
                </option>
              ))}
            </select>
          ) : null}
        </div>
      ))}

      <button
        type="button"
        className="est-btn ep-custom-add"
        disabled={atCap}
        title={atCap ? `An estimate carries up to ${MAX_CUSTOM_LINES} line items` : undefined}
        onClick={() => onChange([...lines, newCustomLineDraft(defaultSide)])}
      >
        <Plus aria-hidden="true" /> Add line item
      </button>

      {permanentTotal > 0 || seasonalCustomTotal > 0 ? (
        <div className="ep-lines">
          {seasonalCustomTotal > 0 ? (
            <div className="ep-line">
              <span className="ep-line-name">Line items · per season</span>
              <span className="ep-line-amount">{formatCurrency(seasonalCustomTotal)}</span>
            </div>
          ) : null}
          {permanentTotal > 0 ? (
            <div className="ep-line">
              <span className="ep-line-name">Line items · one-time</span>
              <span className="ep-line-amount">{formatCurrency(permanentTotal)}</span>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
