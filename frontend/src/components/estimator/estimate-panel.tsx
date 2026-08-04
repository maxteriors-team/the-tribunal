"use client";

/**
 * Rep-facing itemized estimate readout (right column).
 *
 * Every figure here is server-authoritative — it comes straight from the
 * `quotes/estimate` response, never computed on the client. It shows the
 * measured roofline (internal-only), the per-category seasonal decor costs, both
 * headline totals, and the multi-year savings. The client-facing view is the
 * separate `ComparisonCard`.
 *
 * When the workspace sells Christmas as Good/Better/Best packages, the response
 * carries `christmas_packages`; the rep picks one here and the seasonal headline
 * reflects that package's total (matching what the client sees on the share).
 *
 * Standalone line items are edited here too. They are the one thing on this
 * panel the rep types a price for, and they sit *outside* the package ladder:
 * switching Good→Best re-prices the package and leaves the add-ons alone.
 */
import { Plus, X } from "lucide-react";

import {
  MAX_CUSTOM_LINES,
  newCustomLineDraft,
  type CustomLineDraft,
  type CustomLineSide,
} from "@/lib/estimator/custom-lines";
import { resolveSelectedPackage, seasonalTotal } from "@/lib/estimator/packages";
import { formatCurrency } from "@/lib/utils/number";
import type { LinearFeetEstimateResult } from "@/types/estimate";

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
   * Whether this estimate is the one being sold. False when the Quote Builder
   * hosts the designer: that flow prices from the wizard's own document, so a
   * line typed here would never reach the quote — better absent than dropped.
   */
  allowCustomLines: boolean;
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
  allowCustomLines,
}: EstimatePanelProps) {
  const permanent = estimate?.permanent;
  const christmas = estimate?.christmas;
  const decor = christmas?.items ?? [];
  const bothOffered = !!permanent?.enabled && !!christmas?.enabled;
  const savings = Math.abs(estimate?.multi_year_savings ?? 0);
  const permanentWins = bothOffered && (estimate?.multi_year_savings ?? 0) > 0;

  // Good/Better/Best seasonal packages (empty unless the workspace sells them).
  // The rep picks one; when active, that package's total is the seasonal headline
  // in place of the à la carte roofline+decor total.
  const packages = christmas?.enabled ? (estimate?.christmas_packages ?? []) : [];
  const hasPackages = packages.length > 0;
  const selectedPkg = resolveSelectedPackage(packages, selectedPackage);
  const seasonalHeadline = seasonalTotal(
    { total: christmas?.total ?? 0, custom_total: christmas?.custom_total },
    selectedPkg,
  );

  return (
    <div className="ep-panel">
      <div className="ep-title">Estimate</div>

      {!hasDesign ? (
        <p className="ep-empty">
          Pick a product on the left and trace it onto the photo. Pricing updates
          live as you draw
          {allowCustomLines
            ? " — or add a line item below for work that isn’t on the photo."
            : "."}
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

          {hasPackages ? (
            <div className="ep-packages">
              <div className="ep-lines-head">Recommended package</div>
              <p className="ep-pkg-hint">
                The client sees all three. This is the one you&rsquo;re
                recommending, highlighted on their page.
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
                      {pkg.popular ? (
                        <span className="ep-pkg-pop">Most Popular</span>
                      ) : null}
                      {pkg.value_tag ? (
                        <span className="ep-pkg-tag">{pkg.value_tag}</span>
                      ) : null}
                      {pkg.marker ? (
                        <span className="ep-pkg-marker">{pkg.marker}</span>
                      ) : null}
                      <span className="ep-pkg-name">{pkg.name ?? pkg.label}</span>
                      <span className="ep-pkg-total">
                        {formatCurrency(pkg.pricing.total)}
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
          ) : christmas?.enabled && decor.length > 0 ? (
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

      {allowCustomLines ? (
        <CustomLines
          lines={customLines}
          onChange={onChangeCustomLines}
          sides={sides}
          permanentTotal={permanent?.custom_total ?? 0}
          seasonalTotal={christmas?.custom_total ?? 0}
          hasPackages={hasPackages}
        />
      ) : null}

      {hasDesign ? (
        <>
          <div className="ep-totals">
            {permanent?.enabled ? (
              <div className="ep-total-row">
                <span>Permanent · one-time</span>
                <span className="ep-total-amount">
                  {formatCurrency(permanent.total)}
                </span>
              </div>
            ) : null}
            {christmas?.enabled ? (
              <div className="ep-total-row ep-total-grand">
                <span>Seasonal · per year</span>
                <span className="ep-total-amount">
                  {formatCurrency(seasonalHeadline)}
                </span>
              </div>
            ) : null}
          </div>

          {bothOffered && savings > 0 ? (
            <div className="ep-savings">
              <span className="ep-savings-label">
                {permanentWins ? "Permanent saves" : "Difference"} over{" "}
                {estimate?.years ?? 5} seasons
              </span>
              <span className="ep-savings-amount">{formatCurrency(savings)}</span>
            </div>
          ) : null}

          {isFetching && !estimate ? <p className="ep-empty">Pricing…</p> : null}
        </>
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
  hasPackages,
}: {
  lines: CustomLineDraft[];
  onChange: (lines: CustomLineDraft[]) => void;
  sides: EstimateSides;
  permanentTotal: number;
  seasonalTotal: number;
  hasPackages: boolean;
}) {
  // Nothing to bill against: a workspace that sells neither side has no total
  // for a line item to land on.
  if (!sides.permanent && !sides.seasonal) return null;

  const defaultSide: CustomLineSide = sides.seasonal ? "seasonal" : "permanent";
  const bothSides = sides.permanent && sides.seasonal;
  const atCap = lines.length >= MAX_CUSTOM_LINES;

  const patch = (id: string, values: Partial<CustomLineDraft>) =>
    onChange(lines.map((l) => (l.id === id ? { ...l, ...values } : l)));

  return (
    <div className="ep-custom">
      <div className="ep-lines-head">Line items</div>
      <p className="ep-pkg-hint">
        {hasPackages
          ? "Anything that isn’t in the price book. Added on top of whichever package they pick."
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
                onChange={(e) =>
                  patch(line.id, { side: e.target.value as CustomLineSide })
                }
              >
                <option value="seasonal">Per season</option>
                <option value="permanent">One-time</option>
              </select>
            ) : null}
          </div>
        </div>
      ))}

      <button
        type="button"
        className="est-btn ep-custom-add"
        disabled={atCap}
        title={
          atCap
            ? `An estimate carries up to ${MAX_CUSTOM_LINES} line items`
            : undefined
        }
        onClick={() => onChange([...lines, newCustomLineDraft(defaultSide)])}
      >
        <Plus aria-hidden="true" /> Add line item
      </button>

      {permanentTotal > 0 || seasonalCustomTotal > 0 ? (
        <div className="ep-lines">
          {seasonalCustomTotal > 0 ? (
            <div className="ep-line">
              <span className="ep-line-name">Line items · per season</span>
              <span className="ep-line-amount">
                {formatCurrency(seasonalCustomTotal)}
              </span>
            </div>
          ) : null}
          {permanentTotal > 0 ? (
            <div className="ep-line">
              <span className="ep-line-name">Line items · one-time</span>
              <span className="ep-line-amount">
                {formatCurrency(permanentTotal)}
              </span>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
