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
 */
import { resolveSelectedPackage } from "@/lib/estimator/packages";
import { formatCurrency } from "@/lib/utils/number";
import type { LinearFeetEstimateResult } from "@/types/estimate";

interface EstimatePanelProps {
  estimate: LinearFeetEstimateResult | null | undefined;
  isFetching: boolean;
  feet: number;
  calibrated: boolean;
  hasDesign: boolean;
  selectedPackage: string | null;
  onSelectPackage: (key: string) => void;
}

export function EstimatePanel({
  estimate,
  isFetching,
  feet,
  calibrated,
  hasDesign,
  selectedPackage,
  onSelectPackage,
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
  const seasonalTotal = selectedPkg ? selectedPkg.pricing.total : (christmas?.total ?? 0);

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

          {hasPackages ? (
            <div className="ep-packages">
              <div className="ep-lines-head">Seasonal package</div>
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
                  {formatCurrency(seasonalTotal)}
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
