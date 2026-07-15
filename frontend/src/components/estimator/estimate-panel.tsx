"use client";

/**
 * Rep-facing itemized estimate readout (right column).
 *
 * Every figure here is server-authoritative — it comes straight from the
 * `quotes/estimate` response, never computed on the client. It shows the
 * measured roofline (internal-only), the per-category seasonal decor costs, both
 * headline totals, and the multi-year savings. The client-facing view is the
 * separate `ComparisonCard`.
 */
import { formatCurrency } from "@/lib/utils/number";
import type { LinearFeetEstimateResult } from "@/types/estimate";

interface EstimatePanelProps {
  estimate: LinearFeetEstimateResult | null | undefined;
  isFetching: boolean;
  feet: number;
  calibrated: boolean;
  hasDesign: boolean;
}

export function EstimatePanel({
  estimate,
  isFetching,
  feet,
  calibrated,
  hasDesign,
}: EstimatePanelProps) {
  const permanent = estimate?.permanent;
  const christmas = estimate?.christmas;
  const decor = christmas?.items ?? [];
  const bothOffered = !!permanent?.enabled && !!christmas?.enabled;
  const savings = Math.abs(estimate?.multi_year_savings ?? 0);
  const permanentWins = bothOffered && (estimate?.multi_year_savings ?? 0) > 0;

  return (
    <div className="ep-panel">
      <div className="ep-title">Estimate</div>

      {!hasDesign ? (
        <p className="ep-empty">
          Pick a product on the left and trace it onto the photo. Pricing updates
          live as you draw.
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

          {christmas?.enabled && decor.length > 0 ? (
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
                  {formatCurrency(christmas.total)}
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

          {isFetching && !estimate ? (
            <p className="ep-empty">Pricing…</p>
          ) : null}
        </>
      )}
    </div>
  );
}
