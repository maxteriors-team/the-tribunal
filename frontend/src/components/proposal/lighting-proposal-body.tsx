"use client";

/**
 * Rich body for wizard-built proposals on the public page: the Good/Better/
 * Best presentation rendered from the saved `proposal_document` snapshot on a
 * light, print-friendly surface. Echoes the operator wizard's typography
 * (Cormorant display / Montserrat UI) and the workspace's brand colors, while
 * plain quotes keep the flat line-item table.
 */
import { fmt } from "@/components/sales-wizard/document";
import type { WizardDocument } from "@/components/sales-wizard/document";
import type { PublicProposalBranding } from "@/types/proposal";

const SERIF = "var(--font-cormorant), Georgia, serif";

interface LightingProposalBodyProps {
  document: WizardDocument;
  branding: PublicProposalBranding;
}

export function LightingProposalBody({
  document: doc,
  branding,
}: LightingProposalBodyProps) {
  const brand = branding.brand_color || "#0F172A";
  const accent = branding.accent_color || "#B08D3E";

  const first = doc.client?.first_name?.trim() || "";
  const last = doc.client?.last_name?.trim() || "";
  const fullName = [first, last].filter(Boolean).join(" ");
  const residence = last
    ? `The ${last} Residence`
    : fullName
      ? `The ${fullName} Residence`
      : "Your Residence";

  const financing = doc.financing;
  const defaultTerm = financing?.default_term ?? 24;
  const pricedTiers = doc.tiers.filter((t) => t.pricing.base > 0);
  const lowMonthly = pricedTiers.length
    ? Math.min(
        ...pricedTiers.map(
          (t) =>
            t.pricing.monthly_by_term?.[String(defaultTerm)] ??
            t.pricing.monthly_payment,
        ),
      )
    : 0;

  const carePlan = doc.care_plan;
  const careSelected = carePlan
    ? (carePlan.options.find((o) => o.key === carePlan.selected) ??
      carePlan.options.find((o) => o.popular) ??
      carePlan.options[0] ??
      null)
    : null;

  const nightImage =
    typeof doc.night_preview?.image === "string"
      ? doc.night_preview.image
      : null;

  return (
    <div className="space-y-10">
      {/* Hero */}
      <div className="pt-2 text-center">
        <p
          className="text-[10px] font-bold uppercase tracking-[0.35em]"
          style={{ color: accent }}
        >
          {branding.business_name}
        </p>
        <h2
          className="mt-3 text-4xl font-light italic leading-none sm:text-5xl"
          style={{ fontFamily: SERIF, color: brand }}
        >
          {residence}
        </h2>
        <div className="mx-auto mt-5 flex items-center justify-center gap-2">
          <span
            className="block h-px w-10"
            style={{
              background: `linear-gradient(90deg, transparent, ${accent})`,
            }}
          />
          <span
            className="block size-1.5 rotate-45 border"
            style={{ borderColor: accent }}
          />
          <span
            className="block h-px w-10"
            style={{
              background: `linear-gradient(270deg, transparent, ${accent})`,
            }}
          />
        </div>
        <p
          className="mx-auto mt-5 max-w-xl text-lg font-light italic leading-relaxed text-slate-600"
          style={{ fontFamily: SERIF }}
        >
          {first ? `${first}, we` : "We"} walked your property and designed
          this with one goal — to make your home look like it belongs on a
          magazine cover. Every fixture placed intentionally. Every shadow
          considered.
        </p>
      </div>

      {/* Night preview */}
      {nightImage ? (
        <figure className="overflow-hidden rounded-lg border border-slate-200">
          {/* eslint-disable-next-line @next/next/no-img-element -- canvas-composited data URL */}
          <img src={nightImage} alt="Your home at night" className="w-full" />
          <figcaption
            className="border-t border-slate-200 bg-slate-50 px-4 py-2 text-[10px] font-bold uppercase tracking-[0.2em]"
            style={{ color: accent }}
          >
            Your home, after dark — design preview
          </figcaption>
        </figure>
      ) : null}

      {/* Package cards */}
      <div className="grid gap-3 sm:grid-cols-3">
        {doc.tiers.map((tier) => {
          const hasValue = tier.pricing.base > 0;
          const isSelected = tier.key === doc.selected_tier;
          const monthly = tier.pricing.monthly_payment;
          return (
            <div
              key={tier.key}
              className={`relative flex flex-col overflow-hidden rounded-lg border ${
                isSelected ? "shadow-md" : "border-slate-200"
              }`}
              style={isSelected ? { borderColor: brand, borderWidth: 2 } : undefined}
            >
              {tier.popular ? (
                <div
                  className="py-1.5 text-center text-[9px] font-extrabold uppercase tracking-[0.25em] text-white"
                  style={{ backgroundColor: brand }}
                >
                  Most Popular
                </div>
              ) : null}
              <div className="flex flex-1 flex-col p-5">
                <p className="text-[9px] font-bold uppercase tracking-[0.3em] text-slate-400">
                  {tier.label}
                </p>
                <h3
                  className="mt-2 text-3xl font-light italic leading-none"
                  style={{ fontFamily: SERIF, color: brand }}
                >
                  {tier.name ?? tier.label}
                </h3>
                {tier.experience ? (
                  <p className="mt-3 text-sm leading-relaxed text-slate-600">
                    {tier.experience}
                  </p>
                ) : null}
                <div className="my-4 border-y border-slate-200 py-4">
                  <p
                    className="text-4xl font-light leading-none"
                    style={{ fontFamily: SERIF, color: hasValue ? brand : "#94A3B8" }}
                  >
                    {hasValue ? fmt(tier.pricing.cash_total) : "Custom Quote"}
                  </p>
                  <p className="mt-2 text-[10px] font-medium uppercase tracking-[0.15em] text-slate-400">
                    Cash/check · Installed all-inclusive
                  </p>
                  {hasValue && monthly > 0 ? (
                    <p
                      className="mt-2 text-sm italic text-slate-500"
                      style={{ fontFamily: SERIF }}
                    >
                      or ≈ <strong style={{ color: accent }}>{fmt(monthly)}</strong>
                      /mo financed
                    </p>
                  ) : null}
                </div>
                {tier.warranty ? (
                  <p className="mb-3 flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.1em] text-slate-500">
                    <span
                      className="size-1 rounded-full"
                      style={{ backgroundColor: accent }}
                    />
                    {tier.warranty}
                  </p>
                ) : null}
                <ul className="mt-auto space-y-2">
                  {tier.points.map((point, i) => (
                    <li
                      key={i}
                      className="flex items-start gap-2 text-[13px] leading-snug text-slate-600"
                    >
                      <span
                        className="mt-1 text-[8px]"
                        style={{ color: accent }}
                      >
                        —
                      </span>
                      {point}
                    </li>
                  ))}
                </ul>
                {isSelected ? (
                  <p
                    className="mt-4 rounded px-2 py-1 text-center text-[10px] font-bold uppercase tracking-[0.2em] text-white"
                    style={{ backgroundColor: brand }}
                  >
                    Your selected package
                  </p>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>

      {/* Add-on charges */}
      {doc.additional_charges.length ? (
        <div
          className="flex flex-col gap-2 rounded-lg border px-5 py-3 text-sm text-slate-600 sm:flex-row sm:items-center sm:justify-between"
          style={{ borderColor: `${accent}55` }}
        >
          <div>
            {doc.additional_charges.map((charge, i) => (
              <p key={i}>
                + {charge.description} — {fmt(charge.amount)}
              </p>
            ))}
          </div>
          <p
            className="text-base italic"
            style={{ fontFamily: SERIF, color: accent }}
          >
            included in prices above
          </p>
        </div>
      ) : null}

      {/* Care plan */}
      {carePlan && careSelected && carePlan.fixture_count > 0 ? (
        <div
          className="grid overflow-hidden rounded-lg border sm:grid-cols-[1.25fr_1fr]"
          style={{ borderColor: `${accent}66` }}
        >
          <div className="p-6">
            <p
              className="text-[9px] font-bold uppercase tracking-[0.3em]"
              style={{ color: accent }}
            >
              Protect Your Investment
            </p>
            <h3
              className="mt-2 text-3xl font-light italic leading-none"
              style={{ fontFamily: SERIF, color: brand }}
            >
              <em>{careSelected.name}</em> Care Plan
            </h3>
            <p
              className="mt-3 text-2xl font-light"
              style={{ fontFamily: SERIF, color: accent }}
            >
              {fmt(careSelected.price)}{" "}
              <span className="text-xs font-semibold uppercase tracking-[0.1em] text-slate-400">
                / year
              </span>
            </p>
            <ul className="mt-4 space-y-2">
              {[
                `${careSelected.visits} professional maintenance visit${careSelected.visits > 1 ? "s" : ""} every year`,
                careSelected.repair_discount > 0
                  ? `${Math.round(careSelected.repair_discount * 100)}% off any repairs or replacements`
                  : "Cleaning, re-aiming & full system health check",
                `Keeps your ${carePlan.fixture_count}-fixture system looking like the night we installed it`,
              ].map((point, i) => (
                <li
                  key={i}
                  className="flex items-start gap-2 text-sm text-slate-600"
                >
                  <span className="mt-0.5 text-[10px]" style={{ color: accent }}>
                    ◆
                  </span>
                  {point}
                </li>
              ))}
            </ul>
          </div>
          <div className="border-t border-slate-200 bg-slate-50 p-6 sm:border-l sm:border-t-0">
            <p
              className="text-[9px] font-bold uppercase tracking-[0.25em]"
              style={{ color: accent }}
            >
              ★ Potential Savings
            </p>
            <p
              className="mt-2 text-5xl font-light leading-none"
              style={{ fontFamily: SERIF, color: brand }}
            >
              {fmt(careSelected.savings)}
            </p>
            <p className="mt-2 text-[11px] font-semibold uppercase tracking-[0.15em] text-slate-400">
              Estimated First Year
            </p>
            <p
              className="mt-3 text-sm italic text-slate-500"
              style={{ fontFamily: SERIF }}
            >
              Based on professional visits, avoided repairs, and plan
              discounts. An estimate — actual savings vary.
            </p>
          </div>
        </div>
      ) : null}

      {/* Bistro */}
      {doc.bistro && doc.bistro.feet > 0 && doc.bistro.total > 0 ? (
        <div
          className="grid overflow-hidden rounded-lg border sm:grid-cols-[1.25fr_1fr]"
          style={{ borderColor: `${accent}66` }}
        >
          <div className="p-6">
            <p
              className="text-[9px] font-bold uppercase tracking-[0.3em]"
              style={{ color: accent }}
            >
              Elevate Your Outdoor Living
            </p>
            <h3
              className="mt-2 text-3xl font-light italic leading-none"
              style={{ fontFamily: SERIF, color: brand }}
            >
              Bistro String Lighting
            </h3>
            <p
              className="mt-3 text-2xl font-light"
              style={{ fontFamily: SERIF, color: accent }}
            >
              {fmt(doc.bistro.total)}{" "}
              <span className="text-xs font-semibold uppercase tracking-[0.1em] text-slate-400">
                cash/check one-time
              </span>
            </p>
            <ul className="mt-4 space-y-2">
              {[
                doc.bistro.product === "color"
                  ? "Color-changing RGBW — set any scene or color right from your phone"
                  : "Warm-white vintage glow — remote-controlled and fully dimmable",
                `${Math.round(doc.bistro.ordered_ft)} ft of professionally hung, weatherproof string lighting`,
                "Commercial-grade hardware, controller & install — built to last season after season",
              ].map((point, i) => (
                <li
                  key={i}
                  className="flex items-start gap-2 text-sm text-slate-600"
                >
                  <span className="mt-0.5 text-[10px]" style={{ color: accent }}>
                    ◆
                  </span>
                  {point}
                </li>
              ))}
            </ul>
          </div>
          <div className="border-t border-slate-200 bg-slate-50 p-6 sm:border-l sm:border-t-0">
            <p
              className="text-[9px] font-bold uppercase tracking-[0.25em]"
              style={{ color: accent }}
            >
              The Experience
            </p>
            <p
              className="mt-2 text-3xl font-light italic leading-tight"
              style={{ fontFamily: SERIF, color: brand }}
            >
              {Math.round(doc.bistro.feet)} linear ft
            </p>
            <p className="mt-2 text-[11px] font-semibold uppercase tracking-[0.15em] text-slate-400">
              patio &amp; pergola
            </p>
            <p
              className="mt-3 text-sm italic text-slate-500"
              style={{ fontFamily: SERIF }}
            >
              Magazine-cover evenings — dinners, parties, and quiet nights,
              all under a warm canopy of light.
            </p>
          </div>
        </div>
      ) : null}

      {/* Financing */}
      {financing?.enabled && lowMonthly > 0 ? (
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-6 text-center sm:p-8">
          <p
            className="text-[9px] font-bold uppercase tracking-[0.35em]"
            style={{ color: accent }}
          >
            Payment Options
          </p>
          <h3
            className="mx-auto mt-2 max-w-md text-2xl font-normal italic"
            style={{ fontFamily: SERIF, color: brand }}
          >
            {financing.headline ?? "Own the night now — 0% APR financing available."}
          </h3>
          <p
            className="mt-4 text-4xl font-light"
            style={{ fontFamily: SERIF, color: accent }}
          >
            as low as <strong className="font-normal">{fmt(lowMonthly)}</strong>
            <span className="text-lg italic text-slate-500">/month</span>
          </p>
          <p className="mt-2 text-[11px] font-semibold uppercase tracking-[0.1em] text-slate-400">
            over {defaultTerm} months · 0% APR · no interest, ever
          </p>
          {financing.terms.length > 1 && pricedTiers.length ? (
            <div className="mt-5 flex flex-wrap justify-center gap-2">
              {financing.terms.map((term) => {
                const monthly = Math.min(
                  ...pricedTiers.map(
                    (t) =>
                      t.pricing.monthly_by_term?.[String(term)] ??
                      t.pricing.monthly_payment,
                  ),
                );
                return (
                  <div
                    key={term}
                    className="min-w-28 rounded border border-slate-200 bg-white px-4 py-2"
                  >
                    <p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-slate-500">
                      {term} Months
                    </p>
                    <p
                      className="text-lg italic"
                      style={{ fontFamily: SERIF, color: brand }}
                    >
                      {fmt(monthly)}/mo
                    </p>
                  </div>
                );
              })}
            </div>
          ) : null}
          <p className="mx-auto mt-5 max-w-lg text-sm leading-relaxed text-slate-600">
            Cash/check prices are shown first above. If monthly payments fit
            better, financing is available on the full all-inclusive project
            total through {financing.provider}.
          </p>
          {financing.points.length ? (
            <div className="mt-4 flex flex-wrap justify-center gap-x-7 gap-y-2">
              {financing.points.map((point, i) => (
                <p key={i} className="text-xs font-semibold text-slate-600">
                  ✓&nbsp; {point}
                </p>
              ))}
            </div>
          ) : null}
          {financing.disclaimer ? (
            <p className="mx-auto mt-4 max-w-md text-[10px] leading-relaxed text-slate-400">
              {financing.disclaimer}
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
