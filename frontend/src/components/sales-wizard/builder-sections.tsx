"use client";

/**
 * Builder sections for the non-landscape product lines plus the combined
 * grand-total panel. Every money figure comes from the server preview
 * document (`category_sections` / `grand_*`); these components only collect the
 * rep's raw inputs and render the server's numbers.
 */
import type { SeasonalItem } from "@/types/sales-wizard";

import { fmt, type UseSalesWizardReturn } from "./use-sales-wizard";

function section(wizard: UseSalesWizardReturn, key: string) {
  return wizard.document?.category_sections.find((s) => s.key === key) ?? null;
}

/** The live grossed breakdown rows for a category (server-priced). */
function Breakdown({
  wizard,
  categoryKey,
  emptyHint,
}: {
  wizard: UseSalesWizardReturn;
  categoryKey: string;
  emptyHint: string;
}) {
  const sec = section(wizard, categoryKey);
  if (!sec || sec.financed_total <= 0) {
    return <div className="bistro-quote-empty">{emptyHint}</div>;
  }
  return (
    <>
      {(sec.lines ?? []).map((line, i) => (
        <div className="bistro-quote-row" key={i}>
          <span className="bistro-quote-label">{line.label}</span>
          <span className="bistro-quote-val">{fmt(line.line_total)}</span>
        </div>
      ))}
      <div className="bistro-quote-row total">
        <span className="bistro-quote-label">{sec.label} Total</span>
        <span className="bistro-quote-val">{fmt(sec.financed_total)}</span>
      </div>
      {sec.min_applied ? (
        <div className="bistro-min-note">Minimum job charge applied</div>
      ) : null}
    </>
  );
}

// ─── Permanent holiday lighting ────────────────────────────────────────────
export function PermanentSection({ wizard }: { wizard: UseSalesWizardReturn }) {
  const { permanent, setPermanent, pricing } = wizard;
  const cfg = pricing?.permanent;
  return (
    <div className="bistro-block">
      <div className="care-head">
        <div>
          <div className="care-head-label">Year-Round Roofline</div>
          <div className="care-head-title">
            {cfg?.label ?? "Permanent Holiday Lighting"}
          </div>
        </div>
      </div>
      <div className="bistro-subtitle">
        Permanent architectural-grade LED track — app-controlled color for the
        holidays, sports, and everyday accent lighting.
      </div>
      <div className="fields-grid-2">
        <div className="bistro-feet-wrap">
          <label className="bistro-feet-label" htmlFor="perm-feet">
            Roofline Linear Feet
          </label>
          <input
            className="bistro-feet-input"
            id="perm-feet"
            type="number"
            min={0}
            placeholder="0"
            value={permanent.feet}
            onChange={(e) => setPermanent({ feet: e.target.value })}
          />
        </div>
        <div className="bistro-feet-wrap">
          <label className="bistro-feet-label" htmlFor="perm-channels">
            Zones / Channels
          </label>
          <input
            className="bistro-feet-input"
            id="perm-channels"
            type="number"
            min={0}
            placeholder="1"
            value={permanent.channels}
            onChange={(e) => setPermanent({ channels: e.target.value })}
          />
        </div>
      </div>
      <div className="bistro-quote">
        <Breakdown
          wizard={wizard}
          categoryKey="permanent"
          emptyHint="Enter roofline footage to price this line."
        />
      </div>
    </div>
  );
}

// ─── Seasonal Christmas ────────────────────────────────────────────────────
// One decor category (trees/bushes/wreaths/garland/…). `each` items render
// steppers; `per_ft` items (garland) render a linear-feet input. Driven entirely
// by the workspace pricing config so a new add-on needs no code here.
function SeasonalItemGroup({
  wizard,
  item,
}: {
  wizard: UseSalesWizardReturn;
  item: SeasonalItem;
}) {
  const options = item.options ?? [];
  if (!options.length) return null;
  const selection = wizard.christmas.items[item.key] ?? {};
  const isPerFt = item.unit === "per_ft";
  const unitLabel = isPerFt ? "/ ft" : "/ ea";
  return (
    <div className="fixture-section">
      <div className="fixture-section-header">
        <div className="fixture-section-title">{item.label}</div>
      </div>
      <div className="fixture-rows">
        {options.map((rate) => {
          const value = selection[rate.key] ?? 0;
          return (
            <div
              className={`fix-row${value > 0 ? " active-row" : ""}`}
              key={rate.key}
            >
              <div className="fix-name-wrap">
                <div className="fix-name">{rate.name}</div>
                <div className="fix-price">
                  {fmt(rate.price)} {unitLabel}
                </div>
              </div>
              <div className="fix-controls">
                {isPerFt ? (
                  <input
                    className="step-val"
                    type="number"
                    min={0}
                    placeholder="0"
                    aria-label={`${rate.name} linear feet`}
                    value={value || ""}
                    onChange={(e) =>
                      wizard.setSeasonalItem(
                        item.key,
                        rate.key,
                        Number.parseFloat(e.target.value) || 0,
                      )
                    }
                  />
                ) : (
                  <div className="stepper">
                    <button
                      type="button"
                      className="step-btn"
                      onClick={() =>
                        wizard.setSeasonalItem(
                          item.key,
                          rate.key,
                          Math.floor(value) - 1,
                        )
                      }
                    >
                      &#8722;
                    </button>
                    <input
                      className="step-val"
                      type="number"
                      min={0}
                      value={value}
                      onChange={(e) =>
                        wizard.setSeasonalItem(
                          item.key,
                          rate.key,
                          Number.parseInt(e.target.value, 10) || 0,
                        )
                      }
                    />
                    <button
                      type="button"
                      className="step-btn"
                      onClick={() =>
                        wizard.setSeasonalItem(
                          item.key,
                          rate.key,
                          Math.floor(value) + 1,
                        )
                      }
                    >
                      +
                    </button>
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function ChristmasSection({ wizard }: { wizard: UseSalesWizardReturn }) {
  const { christmas, setChristmas, pricing } = wizard;
  const cfg = pricing?.christmas;
  return (
    <div className="bistro-block">
      <div className="care-head">
        <div>
          <div className="care-head-label">Seasonal Install</div>
          <div className="care-head-title">
            {cfg?.label ?? "Christmas Lighting"}
          </div>
        </div>
      </div>
      <div className="bistro-subtitle">
        Professional roofline, trees, bushes, wreaths and garland — installed,
        maintained all season, with optional takedown &amp; storage.
      </div>

      <div className="bistro-feet-wrap">
        <label className="bistro-feet-label" htmlFor="xmas-roof">
          Roofline Linear Feet
        </label>
        <input
          className="bistro-feet-input"
          id="xmas-roof"
          type="number"
          min={0}
          placeholder="0"
          value={christmas.roofline_feet}
          onChange={(e) => setChristmas({ roofline_feet: e.target.value })}
        />
      </div>

      {(cfg?.items ?? []).map((item) => (
        <SeasonalItemGroup key={item.key} wizard={wizard} item={item} />
      ))}

      <div className="xmas-toggles">
        {cfg?.takedown_enabled ? (
          <label className="xmas-toggle">
            <input
              type="checkbox"
              checked={christmas.takedown}
              onChange={(e) => setChristmas({ takedown: e.target.checked })}
            />
            <span>Post-season takedown</span>
          </label>
        ) : null}
        {(cfg?.storage_price ?? 0) > 0 ? (
          <label className="xmas-toggle">
            <input
              type="checkbox"
              checked={christmas.storage}
              onChange={(e) => setChristmas({ storage: e.target.checked })}
            />
            <span>Off-season storage ({fmt(cfg?.storage_price ?? 0)})</span>
          </label>
        ) : null}
      </div>

      <div className="bistro-quote">
        <Breakdown
          wizard={wizard}
          categoryKey="christmas"
          emptyHint="Add roofline footage or decor counts to price this line."
        />
      </div>
    </div>
  );
}

// ─── Combined grand totals (all selected product lines) ────────────────────
export function GrandTotals({ wizard }: { wizard: UseSalesWizardReturn }) {
  const doc = wizard.document;
  const financed = doc?.grand_financed_total ?? 0;
  const monthly = doc?.grand_monthly_payment ?? 0;
  if (financed <= 0) return null;
  return (
    <div className="grand-panel">
      <div className="grand-panel-title">All-In Project Total</div>
      <div className="grand-rows">
        <div className="grand-row lead">
          <span>Financed total</span>
          <strong>{fmt(financed)}</strong>
        </div>
        {monthly > 0 ? (
          <div className="grand-row muted">
            <span>As low as</span>
            <strong>{fmt(monthly)}/mo</strong>
          </div>
        ) : null}
      </div>
    </div>
  );
}
