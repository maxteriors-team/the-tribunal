"use client";

/**
 * Client-facing proposal view (dark/gold premium presentation).
 *
 * Renders the saved `proposal_document` snapshot for any product line the quote
 * builder produces — landscape packages, permanent holiday, bistro/string, and
 * seasonal Christmas — from one generalized layout. Operator controls are
 * swapped for the client's Approve / Decline actions. Plain line-item quotes
 * never reach this component; the page renders them with its simple light sheet.
 *
 * Self-contained: styling + fonts + document helpers all live in this module
 * (`./proposal-theme.css`, `./proposal-fonts`, `./document`), independent of the
 * disposable sales-wizard builder.
 */
import { useMemo, useState } from "react";

import { formatDate } from "@/lib/utils/date";
import type { PublicProposal } from "@/types/proposal";

import {
  ChristmasGuarantee,
  ChristmasIncluded,
  ChristmasSteps,
  ChristmasTrust,
  ChristmasValueProps,
} from "./christmas-sections";
import { DepositPanel } from "./deposit-panel";
import {
  fmt,
  isChristmasProposal,
  proposalValueProps,
  type ProposalDoc,
} from "./document";
import {
  FinancingEstimate,
  financingFromSnapshot,
} from "./financing-estimate";
import { renderTextWithLinks } from "./linkify-text";
import { proposalFontVars } from "./proposal-fonts";
import {
  StandardExperience,
  StandardGuarantee,
  StandardIncluded,
  StandardSteps,
  StandardTrust,
} from "./standard-sections";

import "./proposal-theme.css";

interface ClientProposalViewProps {
  data: PublicProposal;
  document: ProposalDoc;
  justApproved: boolean;
  justDeclined: boolean;
  busy: boolean;
  actionError: boolean;
  /** Accepts the proposal at the package key the client chose. */
  onApprove: (selectedTier: string | null) => void;
  onDecline: (reason: string) => void;
}

export function ClientProposalView({
  data,
  document: doc,
  justApproved,
  justDeclined,
  busy,
  actionError,
  onApprove,
  onDecline,
}: ClientProposalViewProps) {
  const { branding } = data;
  const brandName = branding.business_name;

  const [showDecline, setShowDecline] = useState(false);
  const [declineReason, setDeclineReason] = useState("");

  // Packages the client may pick between, priced server-side. One package is
  // not a choice, so the cards stay presentational in that case.
  const packages = useMemo(() => data.packages ?? [], [data.packages]);
  const choosable = packages.length > 1 && !data.is_decided;
  const packagesByKey = useMemo(
    () => new Map(packages.map((p) => [p.key, p])),
    [packages],
  );
  // Starts on the rep's recommendation and follows the client from there.
  const [chosenTier, setChosenTier] = useState<string | null>(null);
  const selectedTier = chosenTier ?? doc.selected_tier ?? null;
  const chosenPackage = selectedTier
    ? (packagesByKey.get(selectedTier) ?? null)
    : null;

  const onChoose = (key: string) => {
    if (!choosable) return;
    setChosenTier(key);
  };

  // Roving-focus arrow keys, per the ARIA radiogroup pattern.
  const onCardKeyDown = (
    event: React.KeyboardEvent<HTMLDivElement>,
    key: string,
  ) => {
    if (event.key === " " || event.key === "Enter") {
      event.preventDefault();
      onChoose(key);
      return;
    }
    const step =
      event.key === "ArrowRight" || event.key === "ArrowDown"
        ? 1
        : event.key === "ArrowLeft" || event.key === "ArrowUp"
          ? -1
          : 0;
    if (step === 0) return;
    event.preventDefault();
    const at = packages.findIndex((p) => p.key === key);
    const next = packages[(at + step + packages.length) % packages.length];
    if (!next) return;
    onChoose(next.key);
    const card = event.currentTarget.parentElement?.querySelector<HTMLElement>(
      `.pkg-card.${CSS.escape(next.key)}`,
    );
    card?.focus();
  };

  const first = doc.client?.first_name?.trim() || "";
  const last = doc.client?.last_name?.trim() || "";
  const fullName = [first, last].filter(Boolean).join(" ");
  const residence = last
    ? `The ${last} Residence`
    : fullName
      ? `The ${fullName} Residence`
      : "Your Project";

  const hasTiers = doc.tiers.some((t) => t.pricing.base > 0);
  const lowestTier = useMemo(() => {
    const priced = doc.tiers.filter((tier) => tier.pricing.base > 0);
    return priced.reduce<(typeof priced)[number] | null>(
      (lowest, tier) =>
        !lowest || tier.pricing.financed_total < lowest.pricing.financed_total
          ? tier
          : lowest,
      null,
    );
  }, [doc.tiers]);
  // A charge pinned to a tier is only charged when that tier is the one being
  // bought, so the client must not read it under a package it doesn't apply to.
  // Mirrors `charges_for_tier` on the server, including the stale-key fallback:
  // a key naming no tier stays visible rather than silently vanishing.
  const shownCharges = useMemo(() => {
    const known = new Set(doc.tiers.map((tier) => tier.key));
    return doc.additional_charges.filter(
      (charge) =>
        !charge.tier_key ||
        !known.has(charge.tier_key) ||
        charge.tier_key === selectedTier,
    );
  }, [doc.additional_charges, doc.tiers, selectedTier]);

  // A seasonal Christmas quote presents as Christmas: evergreen palette, lights
  // and garland, and copy about the season instead of about a permanent
  // installation. A mixed quote stays neutral (see `isChristmasProposal`).
  const festive = isChristmasProposal(doc);
  const valueProps = proposalValueProps(doc);

  // Seasonal Christmas is sold as one up-front price, so it never shows a
  // monthly estimate. Suppressing it here (rather than server-side) also cleans
  // up quotes already saved with a financing block on the snapshot.
  const financingEstimate = festive
    ? null
    : financingFromSnapshot(
        doc.financing,
        lowestTier?.pricing.monthly_payment ?? doc.grand_monthly_payment,
        lowestTier?.pricing.monthly_by_term ?? {},
      );

  // The client proposal shows one all-inclusive package price. Cash/check
  // figures remain internal; estimated financing uses the shared compliance
  // block so its disclaimer always travels with every monthly figure.
  const priceLabel = "Installed \u00b7 All-inclusive";

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

  // The accept button names what's being accepted and what it costs today, so
  // the last click is never ambiguous about which package was bought.
  const chosenLabel = choosable
    ? (chosenPackage?.name ?? chosenPackage?.label ?? null)
    : null;
  const ctaDeposit = choosable
    ? (chosenPackage?.deposit_amount ?? null)
    : data.deposit_required
      ? (data.deposit_amount ?? null)
      : null;

  return (
    <div
      className={`proposal-view${festive ? " is-christmas" : ""} ${proposalFontVars}`}
    >
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
            &#10003;&nbsp; You approved this proposal. Thank you — we&rsquo;ll be
            in touch shortly to schedule your project.
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
            <img src={branding.logo_url} alt={brandName} className="pp-logo" />
          ) : null}
          <div className="present-eyebrow">{brandName}</div>
          <div className="present-hi">
            Hi, <strong>{first || "there"}</strong>{" "}&#8212;{" "}
            {festive ? "your Christmas lighting plan" : "your custom proposal"}
          </div>
          <div className="present-name">{residence}</div>
          <div className="present-ornament">
            <div className="present-ornament-line" />
            <div className="present-ornament-diamond" />
            <div className="present-ornament-line r" />
          </div>
          <div className="present-tagline">
            {festive ? (
              <>
                {first ? `${first}, this` : "This"}{" "}display was designed
                around your rooflines, your trees, and the way your home should
                look from the street on Christmas Eve.
              </>
            ) : (
              <>
                {first ? `${first}, we` : "We"}{" "}designed this around your
                home and the way you want it to feel &#8212; every detail chosen
                with intention, nothing left to chance.
              </>
            )}
          </div>
        </div>

        <div className="value-bar">
          <div className="value-bar-eyebrow">
            {festive ? "Our Promise" : "Our Approach"}
          </div>
          <div className="value-bar-text">
            {festive ? (
              <>
                You should get to enjoy Christmas.{" "}
                <em>We handle everything else.</em>{" "}The design, the ladders,
                the lights, the maintenance, and the takedown are all ours.
              </>
            ) : (
              <>
                Your home is already beautiful.{" "}
                <em>We&rsquo;re here to make it unforgettable.</em>{" "}Every
                detail is deliberate &#8212; chosen for your home, your style,
                and the way you live.
              </>
            )}
          </div>
        </div>

        {doc.mockups.length ? (
          <div className="pmock-section">
            <div className="section-heading">
              {festive ? "Your Home, Lit Up" : "The Vision for Your Home"}
            </div>
            <div
              className={`pmock-grid${doc.mockups.length === 1 ? " single" : ""}`}
            >
              {doc.mockups.map((m, i) => (
                <figure className="pmock-item" key={i}>
                  {/* eslint-disable-next-line @next/next/no-img-element -- snapshot data URL */}
                  <img src={m.image} alt={m.caption || `Design mockup ${i + 1}`} />
                  {m.caption ? (
                    <figcaption className="pmock-cap">{m.caption}</figcaption>
                  ) : null}
                </figure>
              ))}
            </div>
          </div>
        ) : null}

        {nightImage ? (
          <div className="pnight-section">
            <div className="pnight-frame">
              {/* eslint-disable-next-line @next/next/no-img-element -- canvas-composited data URL */}
              <img src={nightImage} alt="Your home, design preview" />
              <div className="pnight-cap">Your home &#8212; design preview</div>
            </div>
          </div>
        ) : null}

        {hasTiers ? (
          <div
            className="pkg-grid"
            role={choosable ? "radiogroup" : undefined}
            aria-label={choosable ? "Choose your package" : undefined}
            // Columns follow the package count: a two-package quote must not
            // leave a dead third column beside the cards.
            style={
              {
                "--pkg-count": doc.tiers.length,
              } as React.CSSProperties
            }
          >
            {doc.tiers.map((tier) => {
              const hasValue = tier.pricing.base > 0;
              const offer = packagesByKey.get(tier.key);
              // Priced from the server per package, so the card shows the
              // all-in total the client actually pays for that package — not
              // the tier's own subtotal.
              const lead = offer
                ? fmt(offer.total)
                : hasValue
                  ? fmt(tier.pricing.financed_total)
                  : "Custom Quote";
              const isSelected = hasValue && tier.key === selectedTier;
              const isChoice = choosable && Boolean(offer);
              const dueToday = offer?.deposit_amount ?? null;
              return (
                <div
                  className={`pkg-card ${tier.key}${isSelected ? " pp-selected" : ""}${isChoice ? " pp-choosable" : ""}`}
                  key={tier.key}
                  role={isChoice ? "radio" : undefined}
                  aria-checked={isChoice ? isSelected : undefined}
                  tabIndex={isChoice ? (isSelected ? 0 : -1) : undefined}
                  onClick={isChoice ? () => onChoose(tier.key) : undefined}
                  onKeyDown={isChoice ? (e) => onCardKeyDown(e, tier.key) : undefined}
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
                    <div className="pkg-experience">
                      {tier.experience ?? ""}
                    </div>
                    <div className="pkg-price-wrap">
                      <div className="pkg-price">{lead}</div>
                      <div className="pkg-price-label">{priceLabel}</div>
                      {dueToday && dueToday > 0 ? (
                        <div className="pkg-subprice">
                          {`${fmt(dueToday)} due today to start`}
                        </div>
                      ) : null}
                      {/* Independent of the deposit: this line is the only
                          thing pointing at the financing block below, so a
                          package that takes a deposit must not silence it. */}
                      {financingEstimate && tier.pricing.monthly_payment > 0 ? (
                        <div className="pkg-monthly">
                          Estimated payment options below
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
                      &#9733; {choosable ? "Your Choice" : "Your Selected Package"}
                    </div>
                  ) : isChoice ? (
                    <div className="pkg-choose-bar">Choose this package</div>
                  ) : null}
                </div>
              );
            })}
          </div>
        ) : null}
        {choosable && !decided ? (
          <p className="pkg-grid-hint">
            Tap a package to choose it. You can change your mind right up until
            you accept.
          </p>
        ) : null}

        <FinancingEstimate financing={financingEstimate} />

        {shownCharges.length ? (
          <div className="addon-bar">
            <div className="addon-bar-label">
              {shownCharges.map((charge, i) => (
                <span key={charge.description + i}>
                  + {charge.description}{" "}&#8212; {fmt(charge.amount)}
                  {i < shownCharges.length - 1 ? <br /> : null}
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
                      : "Cleaning, tuning & a full system health check",
                    `Keeps your ${carePlan.fixture_count}-fixture system looking like the day we installed it`,
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
                  <span>one-time</span>
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

        {doc.category_sections.length ? (
          <>
            {doc.category_sections.map((sec) => (
              <div className="pcare-section" key={sec.key}>
                <div className="pcare-inner">
                  <div className="pcare-left">
                    <div className="pcare-eyebrow">
                      {sec.key === "christmas"
                        ? "Your Holiday Display"
                        : "Your Quote"}
                    </div>
                    <div className="pcare-name">{sec.label}</div>
                    <div className="pcare-price">
                      {fmt(sec.financed_total)}{" "}
                      <span>one-time</span>
                    </div>
                    <div className="pcare-points">
                      {(sec.lines ?? []).map((line, i) => (
                        <div className="pcare-point" key={i}>
                          <span className="pcare-point-mark">&#9670;</span>
                          <div>
                            {line.label}
                            {line.line_total > 0
                              ? ` \u2014 ${fmt(line.line_total)}`
                              : ""}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                  <div className="pcare-right">
                    <div className="pcare-savings-label">Installed</div>
                    <div
                      className="pcare-savings-amount"
                      style={{ fontSize: "clamp(30px,4.4vw,42px)" }}
                    >
                      {fmt(sec.financed_total)}
                    </div>
                    <div className="pcare-savings-unit">
                      {sec.key === "christmas"
                        ? "Install, maintenance, takedown, and storage included"
                        : "All-inclusive \u00b7 professionally installed"}
                    </div>
                  </div>
                </div>
              </div>
            ))}
            {doc.grand_financed_total > 0 ? (
              <div
                className="grand-panel"
                style={{ maxWidth: 460, margin: "18px auto 0" }}
              >
                <div className="grand-panel-title">All-In Project Total</div>
                <div className="grand-rows">
                  <div className="grand-row lead">
                    <span>Total</span>
                    <strong>{fmt(doc.grand_financed_total)}</strong>
                  </div>
                </div>
              </div>
            ) : null}
          </>
        ) : null}

        {/* The pitch. A seasonal quote sells maintenance, takedown, and
            storage; a permanent one sells design and craftsmanship. Neither
            set of promises is true of the other product, so the whole block
            swaps rather than accumulating conditionals. */}
        {festive ? (
          <>
            <ChristmasValueProps
              brandName={brandName}
              valueProps={valueProps}
            />
            <ChristmasGuarantee />
            <ChristmasIncluded />
            <ChristmasSteps />
            <ChristmasTrust brandName={brandName} />
          </>
        ) : (
          <>
            <StandardExperience brandName={brandName} />
            <StandardGuarantee />
            <StandardIncluded />
            <StandardSteps />
            <StandardTrust brandName={brandName} />
          </>
        )}

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

        {/* While a package is still up for grabs, the deposit is whatever the
            client's current choice costs, and paying goes through accept so
            they're never charged for a package they didn't pick. */}
        <DepositPanel
          data={data}
          amountDue={choosable ? (chosenPackage?.deposit_amount ?? null) : undefined}
          onPayInstead={choosable ? () => onApprove(selectedTier) : undefined}
          payLabel={choosable ? "Accept & Pay Deposit" : undefined}
          busy={busy}
        />

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
                  ? `Let\u2019s bring your project to life, ${first}.`
                  : "Let\u2019s bring your project to life."}
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
                  onClick={() => onApprove(selectedTier)}
                >
                  {busy ? (
                    "Approving…"
                  ) : (
                    <>
                      &#10003;&nbsp;
                      {ctaDeposit && ctaDeposit > 0
                        ? `Accept${chosenLabel ? ` ${chosenLabel}` : ""} \u0026 Pay ${fmt(ctaDeposit)}`
                        : chosenLabel
                          ? `Accept ${chosenLabel}`
                          : "Approve Proposal"}
                    </>
                  )}
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
          <div className="pp-footer-note">
            {renderTextWithLinks(branding.footer)}
          </div>
        ) : null}
      </div>
    </div>
  );
}
