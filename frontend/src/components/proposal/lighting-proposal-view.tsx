"use client";

/**
 * Client-facing view for wizard-built proposals: the same dark/gold
 * presentation the rep shows in the sales wizard (`presentation-screen.tsx`),
 * rendered standalone from the saved `proposal_document` snapshot — with the
 * operator controls swapped for the client's Approve / Decline actions.
 * Plain quotes never reach this component; they keep the light sheet.
 */
import { useMemo, useState } from "react";

import { fmt } from "@/components/sales-wizard/document";
import type { WizardDocument } from "@/components/sales-wizard/document";
import { salesWizardFontVars } from "@/components/sales-wizard/fonts";
import { formatDate } from "@/lib/utils/date";
import type { PublicProposal } from "@/types/proposal";

import "@/components/sales-wizard/theme.css";

interface LightingProposalViewProps {
  data: PublicProposal;
  document: WizardDocument;
  justApproved: boolean;
  justDeclined: boolean;
  busy: boolean;
  actionError: boolean;
  onApprove: () => void;
  onDecline: (reason: string) => void;
}

export function LightingProposalView({
  data,
  document: doc,
  justApproved,
  justDeclined,
  busy,
  actionError,
  onApprove,
  onDecline,
}: LightingProposalViewProps) {
  const { branding } = data;
  const brandName = branding.business_name;

  const financing = doc.financing;
  const [term, setTerm] = useState<number>(financing?.default_term ?? 24);
  const [showDecline, setShowDecline] = useState(false);
  const [declineReason, setDeclineReason] = useState("");

  const first = doc.client?.first_name?.trim() || "";
  const last = doc.client?.last_name?.trim() || "";
  const fullName = [first, last].filter(Boolean).join(" ");
  const residence = last
    ? `The ${last} Residence`
    : fullName
      ? `The ${fullName} Residence`
      : "Your Residence";

  // Lowest-priced package with real money drives the "as low as" figure.
  const lowestTier = useMemo(() => {
    const priced = doc.tiers.filter((t) => t.pricing.base > 0);
    if (!priced.length) return null;
    return priced.reduce((min, t) =>
      t.pricing.financed_total < min.pricing.financed_total ? t : min,
    );
  }, [doc]);
  const monthlyAt = (termMonths: number): number =>
    lowestTier?.pricing.monthly_by_term?.[String(termMonths)] ??
    lowestTier?.pricing.monthly_payment ??
    0;
  const lowMonthly = monthlyAt(term);
  const terms = financing?.terms ?? [];

  const cashEnabled = doc.tiers.some(
    (t) => t.pricing.base > 0 && t.pricing.cash_total < t.pricing.financed_total,
  );
  const priceLabel = cashEnabled
    ? "Cash/check \u00b7 Installed all-inclusive"
    : "Installed \u00b7 All-inclusive";

  const carePlan = doc.care_plan;
  const careSelected = carePlan
    ? (carePlan.options.find((o) => o.key === carePlan.selected) ??
      carePlan.options.find((o) => o.popular) ??
      carePlan.options[0] ??
      null)
    : null;

  const bistro = doc.bistro;
  const bistroTierName = bistro?.tier
    ? bistro.tier.charAt(0).toUpperCase() + bistro.tier.slice(1)
    : "Custom";

  const nightImage =
    typeof doc.night_preview?.image === "string"
      ? doc.night_preview.image
      : null;

  const decided = data.is_decided || justApproved || justDeclined;
  const contactLine = [branding.business_phone, branding.business_email]
    .filter(Boolean)
    .join(" \u00b7 ");

  return (
    <div className={`sales-wizard ${salesWizardFontVars}`}>
      <div className="present-nav no-print">
        <div className="present-nav-brand">
          {`${brandName} · Proposal ${data.number}`}
        </div>
        <div className="present-nav-actions">
          <button
            type="button"
            className="send-email-nav-btn"
            onClick={() => window.print()}
          >
            &#9113; Save as PDF
          </button>
        </div>
      </div>

      <div className="present-body">
        {justApproved ? (
          <div className="pp-banner ok">
            &#10003;&nbsp; You approved this proposal. Thank you — we&rsquo;ll
            be in touch shortly to schedule your installation.
          </div>
        ) : justDeclined ? (
          <div className="pp-banner no">
            You declined this proposal. Thanks for letting us know.
          </div>
        ) : data.is_expired ? (
          <div className="pp-banner">
            This proposal has expired. Please contact us for an updated quote.
          </div>
        ) : null}

        <div className="present-hero">
          {branding.logo_url ? (
            // eslint-disable-next-line @next/next/no-img-element -- workspace-uploaded logo URL
            <img
              src={branding.logo_url}
              alt={brandName}
              className="pp-logo"
            />
          ) : null}
          <div className="present-eyebrow">{brandName}</div>
          <div className="present-hi">
            Hi, <strong>{first || "there"}</strong>{" "}&#8212; your custom
            lighting proposal
          </div>
          <div className="present-name">{residence}</div>
          <div className="present-ornament">
            <div className="present-ornament-line" />
            <div className="present-ornament-diamond" />
            <div className="present-ornament-line r" />
          </div>
          <div className="present-tagline">
            {first ? `${first}, we` : "We"}{" "}walked your property and designed
            this with one goal &#8212; to make your home look like it belongs
            on a magazine cover. Every fixture placed intentionally. Every
            shadow considered.
          </div>
        </div>

        <div className="value-bar">
          <div className="value-bar-eyebrow">Our Design Philosophy</div>
          <div className="value-bar-text">
            Your home is already beautiful.{" "}
            <em>We&rsquo;re here to reveal it after dark.</em>{" "}Every fixture is
            a brush stroke &#8212; the trees, the architecture, the path to
            your door &#8212; all composed into something your neighbors will
            talk about.
          </div>
        </div>

        {nightImage ? (
          <div className="pnight-section">
            <div className="pnight-frame">
              {/* eslint-disable-next-line @next/next/no-img-element -- canvas-composited data URL */}
              <img src={nightImage} alt="Your home at night" />
              <div className="pnight-cap">
                Your home, after dark &#8212; design preview
              </div>
            </div>
          </div>
        ) : null}

        <div className="pkg-grid">
          {doc.tiers.map((tier) => {
            const hasValue = tier.pricing.base > 0;
            const lead = hasValue
              ? fmt(tier.pricing.cash_total)
              : "Custom Quote";
            const isSelected = hasValue && tier.key === doc.selected_tier;
            return (
              <div
                className={`pkg-card ${tier.key}${isSelected ? " pp-selected" : ""}`}
                key={tier.key}
              >
                {tier.popular ? (
                  <div className="pkg-popular-bar">&#9670; Most Popular</div>
                ) : null}
                <div className="pkg-card-topbar" />
                <div className="pkg-card-inner">
                  <div className="pkg-tier-label">{tier.label}</div>
                  {tier.value_tag ? (
                    <div className="pkg-value-tag">{tier.value_tag}</div>
                  ) : null}
                  <div className="pkg-name">{tier.name ?? tier.label}</div>
                  <div className="pkg-experience">{tier.experience ?? ""}</div>
                  <div className="pkg-price-wrap">
                    <div className="pkg-price">{lead}</div>
                    <div className="pkg-price-label">{priceLabel}</div>
                    {hasValue && tier.pricing.monthly_payment > 0 ? (
                      <div className="pkg-monthly">
                        Financing options shown below
                      </div>
                    ) : null}
                  </div>
                  {tier.warranty ? (
                    <div className="pkg-warranty">
                      <span className="pkg-warranty-dot" />
                      {tier.warranty}
                    </div>
                  ) : null}
                  <div className="pkg-points">
                    {tier.points.map((point, i) => (
                      <div className="pkg-point" key={i}>
                        <span className="pkg-point-marker">&#8212;</span>
                        <div>{point}</div>
                      </div>
                    ))}
                  </div>
                </div>
                {isSelected ? (
                  <div className="pkg-selected-bar">
                    &#9733; Your Selected Package
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>

        {doc.additional_charges.length ? (
          <div className="addon-bar">
            <div className="addon-bar-label">
              {doc.additional_charges.map((charge, i) => (
                <span key={i}>
                  + {charge.description}{" "}&#8212; {fmt(charge.amount)}
                  {i < doc.additional_charges.length - 1 ? <br /> : null}
                </span>
              ))}
            </div>
            <div className="addon-bar-amount">included in prices above</div>
          </div>
        ) : null}

        {carePlan && careSelected && carePlan.fixture_count > 0 ? (
          <div className="pcare-section">
            <div className="pcare-inner">
              <div className="pcare-left">
                <div className="pcare-eyebrow">Protect Your Investment</div>
                <div className="pcare-name">
                  <em>{careSelected.name}</em>{" "}Care Plan
                </div>
                <div className="pcare-price">
                  {fmt(careSelected.price)} <span>/ year</span>
                </div>
                <div className="pcare-points">
                  {[
                    `${careSelected.visits} professional maintenance visit${careSelected.visits > 1 ? "s" : ""} every year`,
                    careSelected.repair_discount > 0
                      ? `${Math.round(careSelected.repair_discount * 100)}% off any repairs or replacements`
                      : "Cleaning, re-aiming & full system health check",
                    `Keeps your ${carePlan.fixture_count}-fixture system looking like the night we installed it`,
                  ].map((point, i) => (
                    <div className="pcare-point" key={i}>
                      <span className="pcare-point-mark">&#9670;</span>
                      <div>{point}</div>
                    </div>
                  ))}
                </div>
              </div>
              <div className="pcare-right">
                <div className="pcare-savings-label">
                  &#9733; Potential Savings
                </div>
                <div className="pcare-savings-amount">
                  {fmt(careSelected.savings)}
                </div>
                <div className="pcare-savings-unit">Estimated First Year</div>
                <div className="pcare-savings-basis">
                  Based on professional visits, avoided repairs, and plan
                  discounts. An estimate &#8212; actual savings vary.
                </div>
              </div>
            </div>
          </div>
        ) : null}

        {bistro && bistro.feet > 0 && bistro.total > 0 ? (
          <div className="pcare-section">
            <div className="pcare-inner">
              <div className="pcare-left">
                <div className="pcare-eyebrow">Elevate Your Outdoor Living</div>
                <div className="pcare-name">
                  <em>
                    {bistro.product === "color" ? "Color Changing" : "Classic"}
                  </em>{" "}
                  Bistro Lighting
                </div>
                <div className="pcare-price">
                  {fmt(bistro.total)}{" "}
                  <span>
                    {cashEnabled ? "cash/check one-time" : "one-time"}
                  </span>
                </div>
                <div className="pcare-points">
                  {[
                    bistro.product === "color"
                      ? "Color-changing RGBW — set any scene or color right from your phone"
                      : "Warm-white vintage glow — remote-controlled and fully dimmable",
                    `${Math.round(bistro.ordered_ft)} ft of professionally hung, weatherproof string lighting`,
                    "Commercial-grade hardware, controller & install — built to last season after season",
                  ].map((point, i) => (
                    <div className="pcare-point" key={i}>
                      <span className="pcare-point-mark">&#9670;</span>
                      <div>{point}</div>
                    </div>
                  ))}
                </div>
              </div>
              <div className="pcare-right">
                <div className="pcare-savings-label">The Experience</div>
                <div
                  className="pcare-savings-amount"
                  style={{ fontSize: "clamp(30px,4.4vw,42px)" }}
                >
                  {bistroTierName}{" "}Install
                </div>
                <div className="pcare-savings-unit">
                  {Math.round(bistro.feet)}{" "}linear ft &middot; patio &amp;
                  pergola
                </div>
                <div className="pcare-savings-basis">
                  Magazine-cover evenings &#8212; dinners, parties, and quiet
                  nights, all under a warm canopy of light.
                </div>
              </div>
            </div>
          </div>
        ) : null}

        <div className="wg-section">
          <div className="section-heading">The White Glove Experience</div>
          <div className="wg-grid">
            {[
              [
                "A designer, not a salesperson",
                "Your lighting designer walks every foot of your property, flags every fixture location by hand, and composes the design around your home\u2019s architecture — not a template.",
              ],
              [
                "We treat your home like ours",
                "Shoe covers indoors. Lawns left exactly as we found them — every wire buried, every bed raked, every footprint gone before we pull out of the driveway.",
              ],
              [
                "Night aiming, in person",
                "We return after dark to aim and tune every fixture by eye. Your system isn\u2019t finished when it\u2019s installed — it\u2019s finished when it\u2019s beautiful.",
              ],
              [
                "The reveal walkthrough",
                "Your first look is a guided nighttime walkthrough with your designer. We don\u2019t leave until you\u2019ve seen every scene and love every one.",
              ],
              [
                "One call, handled",
                "A question, a tweak, a fixture nudged by a mower — you call your designer directly. No ticket queues, no call centers.",
              ],
              [
                "Here in ten years",
                "Premium fixtures, trained designers, and a growing local company that stands behind every system it installs — for the long run.",
              ],
            ].map(([title, desc]) => (
              <div className="wg-item" key={title}>
                <div className="wg-item-title">{title}</div>
                <div className="wg-item-desc">{desc}</div>
              </div>
            ))}
          </div>
        </div>

        <div className="guarantee-section">
          <div className="guarantee-badge">
            <div className="guarantee-badge-star">&#9733;</div>
            <div className="guarantee-badge-text">
              Satisfaction
              <br />
              Guaranteed
            </div>
          </div>
          <div className="guarantee-content">
            <div className="guarantee-title">
              <em>Satisfaction</em>{" "}Guaranteed
            </div>
            <div className="guarantee-body">
              We don&rsquo;t consider the job done until you&rsquo;re
              completely happy with your lighting. If anything isn&rsquo;t
              right after installation,{" "}
              <strong>
                we come back and make it right &#8212; no questions asked.
              </strong>{" "}
              Your home deserves to look exactly the way you imagined it.
            </div>
          </div>
        </div>

        <div className="included-section">
          <div className="section-heading">Every Package Includes</div>
          <div className="included-grid">
            {[
              "Professional wire burying & secure connections",
              "Night aiming — every fixture aimed after dark",
              "Custom lighting design for your property",
              "Expert system setup & commissioning",
              "1-year labor warranty on all work",
              "All fixtures installed & ready to enjoy",
            ].map((item) => (
              <div className="included-item" key={item}>
                <span className="included-check">&#9670;</span> {item}
              </div>
            ))}
          </div>
        </div>

        <div className="steps-section">
          <div className="section-heading">How It Works</div>
          <div className="steps-grid">
            <div className="step-card">
              <div className="step-num">I</div>
              <div className="step-title">You Choose</div>
              <div className="step-desc">
                Pick the package that fits your vision and your home.
              </div>
            </div>
            <div className="step-card">
              <div className="step-num">II</div>
              <div className="step-title">We Install</div>
              <div className="step-desc">
                Our team installs every fixture, buries every wire, aims every
                light &#8212; usually in one day.
              </div>
            </div>
            <div className="step-card">
              <div className="step-num">III</div>
              <div className="step-title">You Enjoy</div>
              <div className="step-desc">
                Step outside that night to a home that looks like nothing else
                on the street.
              </div>
            </div>
          </div>
        </div>

        <div className="trust-section">
          <div className="trust-heading">Why {brandName}</div>
          <div className="trust-body">
            We&rsquo;ve designed and installed lighting systems across hundreds
            of homes in this area. Our reps aren&rsquo;t salespeople &#8212;
            they&rsquo;re <strong>lighting designers</strong>. When we walk
            your property, we&rsquo;re thinking about beam angles, focal
            points, and the story your home tells at night. The fixtures are
            just the medium. <strong>The result is the artwork.</strong>
          </div>
        </div>

        {financing?.enabled ? (
          <div className="fin-section">
            <div className="fin-eyebrow">Payment Options</div>
            <div className="fin-headline">
              {financing.headline ??
                "Own the night now — 0% APR financing available."}
            </div>
            {lowMonthly > 0 ? (
              <>
                <div className="fin-figure">
                  as low as <strong>{fmt(lowMonthly)}</strong>
                  <span className="fin-figure-mo">/month</span>
                </div>
                <div className="fin-figure-sub">
                  over {term}{" "}months &middot; 0% APR &middot; no interest, ever
                </div>
              </>
            ) : null}
            {lowMonthly > 0 && terms.length > 1 ? (
              <div className="fin-terms">
                <div className="fin-terms-label">
                  Choose your term — every plan is 0% APR
                </div>
                <div className="fin-term-toggle">
                  {terms.map((t) => (
                    <button
                      key={t}
                      type="button"
                      className={`fin-term-btn${t === term ? " active" : ""}`}
                      onClick={() => setTerm(t)}
                    >
                      <span className="fin-term-term">{t}{" "}Months</span>
                      <span className="fin-term-mo">
                        {fmt(monthlyAt(t))}/mo
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            ) : null}
            <div className="fin-body">
              {cashEnabled
                ? `Cash/check prices are shown first above. If monthly payments fit better, financing is available on the full all-inclusive project total through ${financing.provider}.`
                : `If monthly payments fit better, financing is available on the full all-inclusive project total through ${financing.provider}.`}
            </div>
            <div className="fin-points">
              {financing.points.map((point, i) => (
                <div className="fin-point" key={i}>
                  &#10003;&nbsp; {point}
                </div>
              ))}
            </div>
            {financing.disclaimer ? (
              <div className="fin-disclaimer">{financing.disclaimer}</div>
            ) : null}
          </div>
        ) : null}

        {data.notes ? (
          <div className="pp-terms">
            <div className="section-heading">Notes</div>
            <p>{data.notes}</p>
          </div>
        ) : null}
        {data.terms ? (
          <div className="pp-terms">
            <div className="section-heading">Terms</div>
            <p>{data.terms}</p>
          </div>
        ) : null}

        <div className="cta-section no-print">
          {decided ? (
            <>
              <div className="cta-eyebrow">
                {justApproved || data.status === "approved"
                  ? "Approved"
                  : "Response Recorded"}
              </div>
              <div className="cta-heading">
                {justApproved || data.status === "approved"
                  ? `Thank you${first ? `, ${first}` : ""}.`
                  : "Thanks for letting us know."}
              </div>
              <div className="cta-sub">
                {contactLine
                  ? `Questions? Reach us anytime — ${contactLine}`
                  : "Questions? We\u2019re right here."}
              </div>
            </>
          ) : showDecline ? (
            <>
              <div className="cta-eyebrow">Before You Go</div>
              <div className="cta-heading">Mind telling us why?</div>
              <div className="pp-decline">
                <textarea
                  rows={3}
                  value={declineReason}
                  onChange={(e) => setDeclineReason(e.target.value)}
                  placeholder="Optional: let us know why (helps us improve)…"
                />
                <div className="pp-decline-row">
                  <button
                    type="button"
                    className="cta-btn-danger"
                    disabled={busy}
                    onClick={() => onDecline(declineReason)}
                  >
                    {busy ? "Sending…" : "Confirm Decline"}
                  </button>
                  <button
                    type="button"
                    className="cta-btn-secondary"
                    disabled={busy}
                    onClick={() => setShowDecline(false)}
                  >
                    Cancel
                  </button>
                </div>
              </div>
            </>
          ) : (
            <>
              <div className="cta-eyebrow">Ready to Move Forward</div>
              <div className="cta-heading">
                {first
                  ? `Let\u2019s light your home, ${first}.`
                  : "Let\u2019s light your home."}
              </div>
              <div className="cta-sub">
                {contactLine
                  ? `Questions? Want to adjust the design? ${contactLine}`
                  : "Questions? Want to adjust the design? We\u2019re right here."}
              </div>
              <div className="cta-buttons">
                <button
                  type="button"
                  className="cta-btn-primary"
                  disabled={busy}
                  onClick={onApprove}
                >
                  {busy ? "Approving…" : <>&#10003;&nbsp; Approve Proposal</>}
                </button>
                <button
                  type="button"
                  className="cta-btn-secondary"
                  disabled={busy}
                  onClick={() => setShowDecline(true)}
                >
                  Decline
                </button>
              </div>
            </>
          )}
          {actionError ? (
            <div className="pp-error">
              Something went wrong. Please refresh and try again.
            </div>
          ) : null}
        </div>

        <div className="rep-sig">
          <div className="rep-sig-brand">{brandName}</div>
          <div className="rep-sig-rep">
            {doc.client?.rep_name ? (
              <>
                Prepared personally by <strong>{doc.client.rep_name}</strong>{" "}
                &middot; {brandName}
              </>
            ) : (
              brandName
            )}
          </div>
        </div>

        <div className="pp-meta">
          {[
            `Proposal ${data.number}`,
            data.issue_date ? `Issued ${formatDate(data.issue_date)}` : null,
            data.expiry_date
              ? `Valid until ${formatDate(data.expiry_date)}`
              : null,
          ]
            .filter(Boolean)
            .join(" \u00b7 ")}
          {branding.business_address ? (
            <>
              <br />
              {branding.business_address}
            </>
          ) : null}
          {contactLine ? (
            <>
              <br />
              {contactLine}
            </>
          ) : null}
        </div>
        {branding.footer ? (
          <div className="pp-footer-note">{branding.footer}</div>
        ) : null}
      </div>
    </div>
  );
}
