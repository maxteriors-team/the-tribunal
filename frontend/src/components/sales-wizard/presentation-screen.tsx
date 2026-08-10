"use client";

/**
 * Screen 2 — the client-facing presentation, rendered entirely from the
 * server-computed ProposalDocument (all-inclusive package cards, compliant
 * payment estimates, Care Plan + bistro upsells, the lit design preview).
 *
 * Cash/check figures stay internal to the builder. Financing remains an estimate
 * only: the shared presentation always renders the workspace disclaimer beside
 * every monthly-payment figure.
 *
 * Each service in the design argues for itself here: a quote covering landscape
 * and Christmas shows both value-prop blocks, not one blended list.
 */
import { toast } from "sonner";

import { ServiceValueProps } from "@/components/estimator/service-value-props";
import {
  FinancingEstimate,
  financingFromSnapshot,
} from "@/components/proposal/financing-estimate";

import { AttachPrompt, useAttachPromptActions } from "./attach-prompt";
import { fmt, type UseSalesWizardReturn } from "./use-sales-wizard";

interface PresentationScreenProps {
  wizard: UseSalesWizardReturn;
  brandName: string;
  /**
   * Omitted when the preview is embedded as a builder step: that step's own
   * Back control already returns the rep to Line Items, and a second "Edit"
   * button beside it is two controls for one job.
   */
  onBack?: () => void;
}

export function PresentationScreen({
  wizard,
  brandName,
  onBack,
}: PresentationScreenProps) {
  const doc = wizard.document;
  const pricedTiers = (doc?.tiers ?? []).filter((tier) => tier.pricing.base > 0);
  const lowestTier = pricedTiers.reduce<(typeof pricedTiers)[number] | null>(
    (lowest, tier) =>
      !lowest || tier.pricing.financed_total < lowest.pricing.financed_total
        ? tier
        : lowest,
    null,
  );
  // Seasonal Christmas is sold as one up-front price, never a monthly. The rep
  // preview has to match the client page exactly, or the rep talks a homeowner
  // through a payment option the proposal will not offer them.
  const isChristmas = wizard.activeService === "christmas";
  const financingEstimate = isChristmas
    ? null
    : financingFromSnapshot(
        doc?.financing,
        lowestTier?.pricing.monthly_payment ?? doc?.grand_monthly_payment ?? 0,
        lowestTier?.pricing.monthly_by_term ?? {},
      );

  const client = doc?.client ?? null;
  const first = client?.first_name?.trim() || "";
  const last = client?.last_name?.trim() || "";
  const fullName = [first, last].filter(Boolean).join(" ");
  const residence = last
    ? `The ${last} Residence`
    : fullName
      ? `The ${fullName} Residence`
      : "Your Residence";

  // Presentation mirrors the client proposal: the all-inclusive price only.
  const priceLabel = "Installed \u00b7 All-inclusive";

  const carePlan = doc?.care_plan ?? null;
  const careSelected =
    carePlan?.options.find((o) => o.key === carePlan.selected) ??
    carePlan?.options.find((o) => o.popular) ??
    carePlan?.options[0] ??
    null;

  const bistro = doc?.bistro ?? null;
  const bistroConfig =
    bistro?.product === "classic"
      ? wizard.pricing?.bistro?.classic
      : wizard.pricing?.bistro?.color;
  const bistroTierConfig = wizard.pricing?.bistro?.tiers?.find(
    (t) => t.key === bistro?.tier,
  );

  // Every angle the rep designed, not just the hero shot. Read from wizard
  // state rather than the previewed document: the composites are stripped from
  // the live preview request (they cost pricing nothing and weigh megabytes),
  // so the document echo is empty until save. This is the same list that saves.
  const nightPhotos = wizard.night.images;

  const shareLink = wizard.savedQuote?.public_token
    ? `${window.location.origin}/p/quotes/${wizard.savedQuote.public_token}`
    : null;

  const attach = useAttachPromptActions(wizard);

  const handleSave = async () => {
    if (shareLink) {
      try {
        await navigator.clipboard.writeText(shareLink);
        toast.success("Client link copied");
      } catch {
        toast.error("Could not copy — use the Send step’s link box");
      }
      return;
    }
    try {
      const quote = await wizard.save();
      const link = quote.public_token
        ? `${window.location.origin}/p/quotes/${quote.public_token}`
        : null;
      if (link) {
        try {
          await navigator.clipboard.writeText(link);
          toast.success("Saved — client link copied to clipboard");
        } catch {
          toast.success("Saved — copy the client link from the Send step");
        }
      } else {
        toast.success("Proposal saved");
      }
    } catch (err) {
      // A blocking attach rule reports itself through the prompt below, so the
      // toast must carry the server's reason rather than a generic retry.
      toast.error(attach.saveErrorMessage(err));
    }
  };

  if (!doc) {
    return (
      <div className="screen active" id="screen-present">
        <div className="present-body">
          <div className="wizard-review-intro">Preparing the proposal…</div>
        </div>
      </div>
    );
  }

  return (
    <div className="screen active" id="screen-present">
      <div className="present-nav">
        <div className="present-nav-brand">{brandName}</div>
        <div className="present-nav-actions">
          <button
            type="button"
            className="send-email-nav-btn"
            disabled={wizard.isSaving}
            onClick={() => void handleSave()}
          >
            {wizard.isSaving ? "Saving…" : "\u2605 Save & Copy Link"}
          </button>
          <button
            type="button"
            className="send-email-nav-btn"
            onClick={() => window.print()}
          >
            &#9113; Print / PDF
          </button>
          {onBack ? (
            <button type="button" className="back-btn" onClick={onBack}>
              &#8592; Edit
            </button>
          ) : null}
        </div>
      </div>

      <div className="present-body">
        <div className="present-hero">
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

        {wizard.mockups.length ? (
          <div className="pmock-section">
            <div className="section-heading">The Vision for Your Home</div>
            <div
              className={`pmock-grid${wizard.mockups.length === 1 ? " single" : ""}`}
            >
              {wizard.mockups.map((m, i) => (
                <figure className="pmock-item" key={i}>
                  {/* eslint-disable-next-line @next/next/no-img-element -- in-memory data URL */}
                  <img src={m.image} alt={m.caption || `Design mockup ${i + 1}`} />
                  {m.caption ? (
                    <figcaption className="pmock-cap">{m.caption}</figcaption>
                  ) : null}
                </figure>
              ))}
            </div>
          </div>
        ) : null}

        {nightPhotos.length ? (
          <div className="pnight-section">
            {nightPhotos.map((image, i) => (
              // Index keys: the list is render-only and never reordered here.
              <div className="pnight-frame" key={i}>
                {/* eslint-disable-next-line @next/next/no-img-element -- canvas-composited data URL */}
                <img src={image} alt="Your home at night" />
                <div className="pnight-cap">
                  Your home, after dark &#8212; design preview
                  {nightPhotos.length > 1
                    ? ` (${i + 1} of ${nightPhotos.length})`
                    : ""}
                </div>
              </div>
            ))}
          </div>
        ) : null}

        {wizard.night.services.length ? (
          <div className="pvalue-section">
            <ServiceValueProps
              services={wizard.night.services}
              pricing={wizard.pricing}
              tierKey={wizard.activeTier}
            />
          </div>
        ) : null}

        <div
          className="pkg-grid"
          // Columns follow the package count — no dead column beside the cards.
          style={{ "--pkg-count": doc.tiers.length } as React.CSSProperties}
        >
          {doc.tiers.map((tier) => {
            const cfg = wizard.tierConfig(tier.key);
            const hasValue = tier.pricing.base > 0;
            const lead = hasValue
              ? fmt(tier.pricing.financed_total)
              : "Custom Quote";
            return (
              <div className={`pkg-card ${tier.key}`} key={tier.key}>
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
                    {financingEstimate && tier.pricing.monthly_payment > 0 ? (
                      <div className="pkg-monthly">
                        Estimated payment options below
                      </div>
                    ) : null}
                  </div>
                  {cfg?.warranty ? (
                    <div className="pkg-warranty">
                      <span className="pkg-warranty-dot" />
                      {cfg.warranty}
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
              </div>
            );
          })}
        </div>

        <FinancingEstimate financing={financingEstimate} />

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
                    {(bistroConfig?.name ?? "Bistro Lights").replace(
                      / Bistro Lights$/,
                      "",
                    )}
                  </em>{" "}
                  Bistro Lighting
                </div>
                <div className="pcare-price">
                  {fmt(bistro.total)} <span>one-time</span>
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
                  {bistroTierConfig?.name ?? "Custom"}{" "}Install
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

        {wizard.attachWarning && !shareLink && (
          <AttachPrompt
            warning={wizard.attachWarning}
            busy={wizard.isSaving}
            onAdd={attach.add}
            onDismiss={attach.dismiss}
          />
        )}

        <div className="cta-section">
          <div className="cta-eyebrow">Ready to Move Forward</div>
          <div className="cta-heading">
            {first ? `Let\u2019s light your home, ${first}.` : "Let\u2019s light your home."}
          </div>
          <div className="cta-sub">
            Questions? Want to adjust the design? We&rsquo;re right here.
          </div>
          <div className="cta-buttons">
            <button
              type="button"
              className="cta-btn-primary"
              disabled={wizard.isSaving}
              onClick={() => void handleSave()}
            >
              &#9733;&nbsp;{" "}
              {shareLink ? "Copy Client Link" : "Save & Get Client Link"}
            </button>
          </div>
        </div>

        <div className="rep-sig">
          <div className="rep-sig-brand">{brandName}</div>
          <div className="rep-sig-rep">
            {client?.rep_name ? (
              <>
                Prepared personally by <strong>{client.rep_name}</strong>{" "}
                &middot; {brandName}
              </>
            ) : (
              brandName
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
