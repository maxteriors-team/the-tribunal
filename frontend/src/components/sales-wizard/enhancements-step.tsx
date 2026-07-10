"use client";

/**
 * Step 4 — Enhancements: Care Plan, bistro string lighting, night preview.
 * Care/bistro money comes from the server preview document; only the
 * per-foot *display* rates on the complexity buttons are derived from config
 * (same gross-up the server applies), never totals.
 */
import { useRef, useState } from "react";

import {
  fmt,
  fmt2,
  MAX_MOCKUPS,
  type UseSalesWizardReturn,
} from "./use-sales-wizard";

interface EnhancementsStepProps {
  wizard: UseSalesWizardReturn;
  onOpenNight: () => void;
}

/**
 * Design-mockup gallery uploader. Images are downscaled in the browser and held
 * as data URLs; they ride into the saved snapshot on save and render as a
 * gallery on both the rep preview and the client proposal.
 */
function MockupsBlock({ wizard }: { wizard: UseSalesWizardReturn }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const mockups = wizard.mockups;
  const atCap = mockups.length >= MAX_MOCKUPS;

  const onPick = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || !files.length) return;
    setBusy(true);
    try {
      await wizard.addMockupFiles(files);
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  return (
    <div className="care-block mock-block">
      <div className="care-head">
        <div>
          <div className="care-head-label">Add Design Mockups</div>
          <div className="care-head-title">Visual Mockups</div>
        </div>
        <div className="mock-count">
          {mockups.length} / {MAX_MOCKUPS}
        </div>
      </div>
      <div className="bistro-subtitle">
        Upload renderings or photos of this project. They appear as a gallery on
        the client proposal &#8212; your most persuasive, visual page.
      </div>
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        multiple
        hidden
        onChange={onPick}
      />
      {mockups.length ? (
        <div className="mock-grid">
          {mockups.map((m, i) => (
            <div className="mock-tile" key={i}>
              {/* eslint-disable-next-line @next/next/no-img-element -- in-memory data URL */}
              <img src={m.image} alt={`Mockup ${i + 1}`} />
              <button
                type="button"
                className="mock-del"
                onClick={() => wizard.removeMockup(i)}
                aria-label="Remove mockup"
              >
                &times;
              </button>
              <input
                className="mock-cap-input"
                type="text"
                maxLength={160}
                placeholder="Caption (optional)"
                value={m.caption}
                onChange={(e) => wizard.setMockupCaption(i, e.target.value)}
              />
            </div>
          ))}
        </div>
      ) : null}
      <button
        type="button"
        className="mock-add"
        disabled={atCap || busy}
        onClick={() => inputRef.current?.click()}
      >
        {busy
          ? "Processing\u2026"
          : atCap
            ? `Maximum ${MAX_MOCKUPS} images added`
            : "\uFF0B Add Mockup Images"}
      </button>
    </div>
  );
}

/** Combined back-end buffer used for display-only per-unit rates. */
function displayBuffer(wizard: UseSalesWizardReturn): number {
  const financing = wizard.pricing?.financing;
  const commission = wizard.pricing?.commission;
  const fee = financing?.enabled ? (financing.fee_buffer ?? 0) : 0;
  const com =
    commission?.enabled && commission.in_price ? (commission.rate ?? 0) : 0;
  return Math.max(0, Math.min(0.95, fee + com));
}

function grossRate(wizard: UseSalesWizardReturn, rate: number): number {
  const buffer = displayBuffer(wizard);
  return buffer > 0 ? rate / (1 - buffer) : rate;
}

/** Non-transformer fixture count of the headline tier (the auto count). */
function autoCount(wizard: UseSalesWizardReturn): number {
  const doc = wizard.document;
  if (!doc?.headline_tier) return 0;
  const view = doc.tiers.find((t) => t.key === doc.headline_tier);
  if (!view) return 0;
  return Math.round(
    view.lines
      .filter((l) => !l.transformer)
      .reduce((sum, l) => sum + l.quantity, 0),
  );
}

function savingsBasis(
  wizard: UseSalesWizardReturn,
  option: { visits: number; repair_discount: number },
  count: number,
): string {
  const savings = wizard.pricing?.savings;
  const perVisit = savings?.per_visit_value ?? 0;
  const avoided = Math.round(
    count * (savings?.avoided_repair_per_fixture ?? 0),
  );
  const repairSpend = count * (savings?.assumed_repair_spend_per_fixture ?? 0);
  const parts: string[] = [];
  if (option.visits > 0) {
    parts.push(
      `${fmt(option.visits * perVisit)} in maintenance visits (${option.visits} × ≈${fmt(perVisit)})`,
    );
  }
  parts.push(`${fmt(avoided)} in avoided repairs (${count} fixtures)`);
  if (option.repair_discount > 0) {
    parts.push(
      `${Math.round(option.repair_discount * 100)}% off repairs (≈${fmt(Math.round(repairSpend * option.repair_discount))})`,
    );
  }
  return `Estimated first-year value: ${parts.join(" + ")}. Estimate only — actual savings vary.`;
}

export function EnhancementsStep({ wizard, onOpenNight }: EnhancementsStepProps) {
  const {
    pricing,
    document,
    carePlanTier,
    setCarePlanTier,
    careCountManual,
    setCareCountManual,
    bistro,
    setBistro,
  } = wizard;

  const carePlan = document?.care_plan;
  const options = carePlan?.options ?? [];
  const selected =
    options.find((o) => o.key === carePlanTier) ?? options[0] ?? null;
  const count = carePlan?.fixture_count ?? 0;
  const auto = autoCount(wizard);

  const bistroConfig = pricing?.bistro;
  const bistroProductConfig =
    bistro.product === "classic" ? bistroConfig?.classic : bistroConfig?.color;
  const bistroDoc = document?.bistro ?? null;

  const showCare = wizard.hasCategory("landscape");
  const showBistro = wizard.hasCategory("bistro");

  return (
    <>
      {/* ── Design mockups (all quotes) ── */}
      <MockupsBlock wizard={wizard} />

      {/* ── Care Plan (landscape) ── */}
      {showCare ? (
      <div className="care-block">
        <div className="care-head">
          <div>
            <div className="care-head-label">Add a Maintenance Plan</div>
            <div className="care-head-title">Care Plan</div>
          </div>
          <div className="care-count-wrap">
            <div className="care-count-label">
              Fixtures
              <br />
              in system
            </div>
            <input
              className="care-count-input"
              type="number"
              min={0}
              value={careCountManual ?? count}
              onChange={(e) => {
                const v = Number.parseInt(e.target.value, 10);
                setCareCountManual(
                  Number.isNaN(v) ? 0 : Math.max(0, Math.min(999, v)),
                );
              }}
            />
            <button
              type="button"
              className="care-auto-btn"
              title="Auto-fill from proposal"
              onClick={() => setCareCountManual(null)}
            >
              Auto ({auto})
            </button>
          </div>
        </div>
        <div className="care-tiers">
          {options.map((option) => (
            <button
              type="button"
              key={option.key}
              className={`care-tier${option.key === selected?.key ? " selected" : ""}`}
              onClick={() => setCarePlanTier(option.key)}
            >
              {option.popular ? (
                <div className="care-tier-pop">Most Popular</div>
              ) : null}
              <div className="care-tier-name">{option.name}</div>
              <div className="care-tier-price">{fmt(option.price)}</div>
              <div className="care-tier-per">per year</div>
              <div className="care-tier-blurb">{option.blurb}</div>
            </button>
          ))}
          {!options.length ? (
            <div className="bistro-quote-empty">Pricing…</div>
          ) : null}
        </div>
        {selected ? (
          <div className="care-savings">
            <div>
              <div className="care-savings-label">&#9733; Potential Savings</div>
              <div className="care-savings-basis">
                {savingsBasis(wizard, selected, count)}
              </div>
            </div>
            <div className="care-savings-amount">
              {fmt(selected.savings)}
              <small>First Year &middot; {selected.name}</small>
            </div>
          </div>
        ) : null}
      </div>
      ) : null}

      {/* ── Bistro string lighting (bistro line) ── */}
      {showBistro && bistroConfig?.enabled && bistroConfig.tiers?.length ? (
        <div className="bistro-block">
          <div className="care-head">
            <div>
              <div className="care-head-label">Patio &amp; Pergola Add-On</div>
              <div className="care-head-title">Bistro String Lighting</div>
            </div>
          </div>
          <div className="bistro-subtitle">
            {bistroProductConfig?.subtitle ?? ""}
          </div>
          <div className="bistro-prod-toggle">
            {(
              [
                ["color", "Color Changing"],
                ["classic", "Classic (Dimmable)"],
              ] as const
            ).map(([key, label]) => (
              <button
                key={key}
                type="button"
                className={`bistro-prod-btn${bistro.product === key ? " active" : ""}`}
                onClick={() => setBistro({ product: key })}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="care-head-label" style={{ margin: "18px 0 8px" }}>
            Installation Complexity
          </div>
          <div className="bistro-tiers">
            {bistroConfig.tiers.map((tier) => {
              const rate =
                bistro.product === "classic"
                  ? (tier.classic_per_ft ?? 0)
                  : (tier.per_ft ?? 0);
              return (
                <button
                  key={tier.key}
                  type="button"
                  className={`bistro-tier-btn${bistro.tier === tier.key ? " active" : ""}`}
                  onClick={() => setBistro({ tier: tier.key })}
                >
                  <div className="bistro-tier-name">{tier.name}</div>
                  <div className="bistro-tier-desc">{tier.desc}</div>
                  <div className="bistro-tier-rate">
                    {fmt2(grossRate(wizard, rate))} / ft
                  </div>
                </button>
              );
            })}
          </div>
          <div className="bistro-feet-wrap">
            <label className="bistro-feet-label" htmlFor="bistro-feet">
              Linear Feet
            </label>
            <input
              className="bistro-feet-input"
              id="bistro-feet"
              type="number"
              min={0}
              placeholder="0"
              value={bistro.feet}
              onChange={(e) => setBistro({ feet: e.target.value })}
            />
          </div>
          <div className="bistro-quote">
            {!bistroDoc || bistroDoc.feet <= 0 ? (
              <div className="bistro-quote-empty">
                Enter linear feet to price this add-on.
              </div>
            ) : (
              <>
                {bistroDoc.lines.map((line, i) =>
                  line.note ? (
                    <div className="bistro-coverage-note" key={i}>
                      {line.note}
                    </div>
                  ) : (
                    <div className="bistro-quote-row" key={i}>
                      <span className="bistro-quote-label">{line.label}</span>
                      <span className="bistro-quote-val">
                        {line.detail ?? ""}
                      </span>
                    </div>
                  ),
                )}
                <div className="bistro-quote-row">
                  <span className="bistro-quote-label">
                    {bistroProductConfig?.name ?? "String lighting"}
                  </span>
                  <span className="bistro-quote-val">
                    {fmt(bistroDoc.lights_cost)}
                  </span>
                </div>
                <div className="bistro-quote-row">
                  <span className="bistro-quote-label">
                    Hardware &amp; controller
                  </span>
                  <span className="bistro-quote-val">
                    {fmt(bistroDoc.hardware)}
                  </span>
                </div>
                <div className="bistro-quote-row total">
                  <span className="bistro-quote-label">Bistro Total</span>
                  <span className="bistro-quote-val">
                    {fmt(bistroDoc.total)}
                  </span>
                </div>
                {bistroDoc.min_applied ? (
                  <div className="bistro-min-note">
                    Minimum job charge of {fmt(bistroDoc.minimum)}{" "}applied
                  </div>
                ) : null}
              </>
            )}
          </div>
        </div>
      ) : null}

      {showCare ? (
        <button
          type="button"
          className="night-launch-btn"
          onClick={onOpenNight}
        >
          &#9789;&nbsp; Night Mode &#8212; Show It Lit at Night
        </button>
      ) : null}
    </>
  );
}
