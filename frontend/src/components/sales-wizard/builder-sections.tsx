"use client";

/**
 * Builder sections for the non-landscape product lines plus the combined
 * grand-total panel. Every money figure comes from the server preview
 * document (`category_sections` / `grand_*`); these components only collect the
 * rep's raw inputs and render the server's numbers.
 */
import {
  seasonalIconForCategory,
  tintSurface,
} from "@/lib/estimator/seasonal-icons";
import type { ChristmasConfig, SeasonalItem } from "@/types/sales-wizard";

import { fmt, type UseSalesWizardReturn } from "./use-sales-wizard";

/** One Good/Better/Best seasonal package (derived from the generated config type). */
type ChristmasPackage = NonNullable<ChristmasConfig["packages"]>[number];

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
  const { Icon, tint } = seasonalIconForCategory(item.key);
  return (
    <div className="fixture-section">
      <div className="fixture-section-header">
        <div className="fixture-section-title-wrap">
          <span
            className="fixture-section-icon"
            style={{ color: tint, background: tintSurface(tint) }}
            aria-hidden="true"
          >
            <Icon className="fix-icon-glyph" />
          </span>
          <div className="fixture-section-title">{item.label}</div>
        </div>
      </div>
      <div className="fixture-rows">
        {options.map((rate) => {
          const value = selection[rate.key] ?? 0;
          return (
            <div
              className={`fix-row${value > 0 ? " active-row" : ""}`}
              key={rate.key}
            >
              <span
                className="fix-icon"
                style={{ color: tint, background: tintSurface(tint) }}
                aria-hidden="true"
              >
                <Icon className="fix-icon-glyph" />
              </span>
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

// Low→high package order: config `package_order` first, then declared order —
// mirrors the backend so the last entry is the most inclusive package.
function orderChristmasPackages(cfg: ChristmasConfig): ChristmasPackage[] {
  const packages = cfg.packages ?? [];
  const byKey = new Map(packages.map((p) => [p.key, p] as const));
  const ordered: ChristmasPackage[] = [];
  for (const key of cfg.package_order ?? []) {
    const pkg = byKey.get(key);
    if (pkg && !ordered.includes(pkg)) ordered.push(pkg);
  }
  for (const pkg of packages) if (!ordered.includes(pkg)) ordered.push(pkg);
  return ordered;
}

// Selectable Good/Better/Best seasonal package cards. The rep picks one; the
// shared roofline + decor controls below feed whichever package is priced.
// Mirrors the landscape tier cards (care-tier pattern) — popular badge, points,
// value tag. The server prices only the *selected* package into the christmas
// section, so the live total shows on the active card (“—” on the rest).
function ChristmasPackageCards({ wizard }: { wizard: UseSalesWizardReturn }) {
  const cfg = wizard.pricing?.christmas;
  if (!cfg) return null;
  const ordered = orderChristmasPackages(cfg);
  if (!ordered.length) return null;
  // Highlight the rep's explicit pick, else the most-inclusive package — the
  // same fallback the server uses when `selected_package` is unset, so the
  // highlighted card always matches the priced christmas-section total.
  const picked = wizard.christmas.selected_package;
  const selectedKey =
    picked && ordered.some((p) => p.key === picked)
      ? picked
      : (ordered[ordered.length - 1]?.key ?? "");
  const total = section(wizard, "christmas")?.financed_total ?? 0;
  return (
    <div className="care-tiers">
      {ordered.map((pkg) => {
        const isSelected = pkg.key === selectedKey;
        const tierLabel = [pkg.marker, pkg.card_tier ?? pkg.label]
          .filter(Boolean)
          .join("\u00a0 ");
        const points = pkg.points ?? [];
        return (
          <button
            type="button"
            key={pkg.key}
            className={`care-tier${isSelected ? " selected" : ""}`}
            aria-pressed={isSelected}
            onClick={() => wizard.setChristmasPackage(pkg.key)}
          >
            {pkg.popular ? (
              <div className="care-tier-pop">Most Popular</div>
            ) : null}
            {pkg.value_tag ? (
              <div className="pkg-value-tag">{pkg.value_tag}</div>
            ) : null}
            {tierLabel ? (
              <div className="care-tier-per">{tierLabel}</div>
            ) : null}
            <div className="care-tier-name">{pkg.name ?? pkg.label}</div>
            {pkg.card_tier && pkg.label ? (
              <div className="care-tier-blurb">{pkg.label}</div>
            ) : null}
            <div className="care-tier-price">
              {isSelected && total > 0 ? fmt(total) : "\u2014"}
            </div>
            <div className="care-tier-per">Package total</div>
            {pkg.experience ? (
              <div className="care-tier-blurb">{pkg.experience}</div>
            ) : null}
            {points.length ? (
              <div className="pkg-points">
                {points.map((point, i) => (
                  <div className="pkg-point" key={i}>
                    <span className="pkg-point-marker">&#8212;</span>
                    <div>{point}</div>
                  </div>
                ))}
              </div>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}

export function ChristmasSection({ wizard }: { wizard: UseSalesWizardReturn }) {
  const { christmas, setChristmas, pricing } = wizard;
  const cfg = pricing?.christmas;
  const packagesEnabled = Boolean(cfg?.packages_enabled);
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
        {packagesEnabled
          ? "Choose a Good / Better / Best package, then enter the roofline and decor once — your selected package prices live off your workspace rates."
          : "Professional roofline, trees, bushes, wreaths and garland — installed, maintained all season, with optional takedown & storage."}
      </div>

      {packagesEnabled ? <ChristmasPackageCards wizard={wizard} /> : null}

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
