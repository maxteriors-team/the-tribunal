"use client";

/**
 * Screen 1 — the 5-step operator wizard (Client → Design → Story → Add-ons →
 * Review). Ported from the uploaded wizard's #screen-calc; the Jobber/Zapier
 * paths are replaced by "save → shareable client link" on the review step.
 */
import { useState } from "react";
import { toast } from "sonner";

import { DesignStep, MiniTotals } from "./design-step";
import { EnhancementsStep } from "./enhancements-step";
import { StoryStep } from "./story-step";
import { fmt, type ClientDraft, type UseSalesWizardReturn } from "./use-sales-wizard";

export type WizardStepId =
  | "client"
  | "design"
  | "story"
  | "enhancements"
  | "review";

const STEPS: { id: WizardStepId; num: string; label: string }[] = [
  { id: "client", num: "01", label: "Client" },
  { id: "design", num: "02", label: "Design" },
  { id: "story", num: "03", label: "Story" },
  { id: "enhancements", num: "04", label: "Add-ons" },
  { id: "review", num: "05", label: "Review" },
];

interface CalculatorScreenProps {
  wizard: UseSalesWizardReturn;
  brandName: string;
  onPresent: () => void;
  onOpenNight: () => void;
}

interface FieldProps {
  wizard: UseSalesWizardReturn;
  field: keyof ClientDraft;
  label: string;
  placeholder: string;
  type?: string;
}

function ClientField({ wizard, field, label, placeholder, type }: FieldProps) {
  return (
    <div className="field-wrap">
      <div className="field-label">{label}</div>
      <input
        className="field-input"
        type={type ?? "text"}
        placeholder={placeholder}
        autoComplete="off"
        value={wizard.client[field]}
        onChange={(e) => wizard.setClientField(field, e.target.value)}
      />
    </div>
  );
}

export function CalculatorScreen({
  wizard,
  brandName,
  onPresent,
  onOpenNight,
}: CalculatorScreenProps) {
  const [step, setStep] = useState<WizardStepId>("client");
  const stepIndex = STEPS.findIndex((s) => s.id === step);

  const goTo = (id: WizardStepId) => {
    setStep(id);
    window.scrollTo(0, 0);
  };
  const goNext = () =>
    goTo(STEPS[Math.min(stepIndex + 1, STEPS.length - 1)].id);
  const goPrev = () => goTo(STEPS[Math.max(stepIndex - 1, 0)].id);

  const { document: doc, pricing } = wizard;
  const order = pricing?.tier_order?.length
    ? pricing.tier_order
    : (pricing?.tiers ?? []).map((t) => t.key);
  const commissionRate = pricing?.commission?.enabled
    ? (pricing.commission.rate ?? 0)
    : 0;
  const ratePct = Math.round(commissionRate * 100);

  const shareLink = wizard.savedQuote?.public_token
    ? `${window.location.origin}/p/quotes/${wizard.savedQuote.public_token}`
    : null;

  const handleSave = async () => {
    try {
      const quote = await wizard.save();
      toast.success("Proposal saved — client link ready");
      return quote;
    } catch {
      toast.error("Could not save the proposal. Please try again.");
      return null;
    }
  };

  const copyShareLink = async () => {
    if (!shareLink) return;
    try {
      await navigator.clipboard.writeText(shareLink);
      toast.success("Client link copied");
    } catch {
      toast.error("Could not copy — select the link text instead");
    }
  };

  return (
    <div className="screen active" id="screen-calc">
      <div>
        <div className="calc-header">
          <div className="calc-wordmark">
            <div className="calc-wordmark-line" />
            <div className="calc-wordmark-text">{brandName}</div>
            <div className="calc-wordmark-line" />
          </div>
          <div className="calc-title">
            <em>Sales</em>{" "}Wizard
          </div>
          <div className="calc-rule" />
          <div className="calc-sub">
            Step through the proposal, then preview or send
          </div>
        </div>

        <div className="wizard-progress" aria-label="Sales wizard progress">
          {STEPS.map((s, i) => (
            <button
              key={s.id}
              type="button"
              className={`wizard-progress-btn${s.id === step ? " active" : ""}${i < stepIndex ? " done" : ""}`}
              aria-current={s.id === step ? "step" : "false"}
              onClick={() => goTo(s.id)}
            >
              <span className="wizard-step-num">{s.num}</span>
              <span className="wizard-step-label">{s.label}</span>
            </button>
          ))}
        </div>

        <div className="wizard-shell">
          {/* ── Step 1: Client ── */}
          <section className={`wizard-step${step === "client" ? " active" : ""}`}>
            <div className="wizard-step-heading">
              <div className="wizard-kicker">Step 1 of 5</div>
              <div className="wizard-title">
                <em>Client</em>{" "}Details
              </div>
              <div className="wizard-copy">
                Capture the client, property, and rep info once. These fields
                feed the proposal and the saved quote.
              </div>
            </div>
            <div className="fields-block">
              <div className="fields-block-label">Client Information</div>
              <div className="fields-grid-2">
                <ClientField wizard={wizard} field="first_name" label="First Name" placeholder="Sarah" />
                <ClientField wizard={wizard} field="last_name" label="Last Name" placeholder="Henderson" />
              </div>
              <div className="fields-grid-3">
                <ClientField wizard={wizard} field="email" label="Client Email" placeholder="sarah@email.com" type="email" />
                <ClientField wizard={wizard} field="phone" label="Client Phone" placeholder="(248) 555-0000" type="tel" />
                <ClientField wizard={wizard} field="rep_name" label="Your Name" placeholder="Rep name" />
              </div>
              <div className="fields-grid-3" style={{ gridTemplateColumns: "1fr" }}>
                <ClientField wizard={wizard} field="street" label="Property Street" placeholder="123 Oak Lane" />
              </div>
              <div className="fields-grid-3">
                <ClientField wizard={wizard} field="city" label="City" placeholder="Birmingham" />
                <ClientField wizard={wizard} field="state" label="State" placeholder="MI" />
                <ClientField wizard={wizard} field="zip" label="Zip" placeholder="48009" />
              </div>
            </div>
            <div className="wizard-nav single">
              <span className="wizard-nav-spacer" />
              <button type="button" className="wizard-nav-btn primary" onClick={goNext}>
                Next: Design Packages
              </button>
            </div>
          </section>

          {/* ── Step 2: Design ── */}
          <section className={`wizard-step${step === "design" ? " active" : ""}`}>
            <div className="wizard-step-heading">
              <div className="wizard-kicker">Step 2 of 5</div>
              <div className="wizard-title">
                <em>Design</em>{" "}Packages
              </div>
              <div className="wizard-copy">
                Build Good / Better / Best options with fixture counts. Add any
                custom job charges here so every package total stays accurate.
              </div>
            </div>
            <DesignStep wizard={wizard} />
            <div className="wizard-nav">
              <button type="button" className="wizard-nav-btn secondary" onClick={goPrev}>
                Back
              </button>
              <button type="button" className="wizard-nav-btn primary" onClick={goNext}>
                Next: Sales Story
              </button>
            </div>
          </section>

          {/* ── Step 3: Story ── */}
          <section className={`wizard-step${step === "story" ? " active" : ""}`}>
            <div className="wizard-step-heading">
              <div className="wizard-kicker">Step 3 of 5</div>
              <div className="wizard-title">
                <em>Sales</em>{" "}Story
              </div>
              <div className="wizard-copy">
                Use this as the in-home slideshow: set the agenda, teach the
                design, frame the value, then make Good / Better / Best feel
                like a simple decision.
              </div>
            </div>
            <StoryStep wizard={wizard} />
            <div className="wizard-nav">
              <button type="button" className="wizard-nav-btn secondary" onClick={goPrev}>
                Back to Design
              </button>
              <button type="button" className="wizard-nav-btn primary" onClick={goNext}>
                Next: Add-ons
              </button>
            </div>
          </section>

          {/* ── Step 4: Enhancements ── */}
          <section className={`wizard-step${step === "enhancements" ? " active" : ""}`}>
            <div className="wizard-step-heading">
              <div className="wizard-kicker">Step 4 of 5</div>
              <div className="wizard-title">
                <em>Enhance</em>{" "}the Proposal
              </div>
              <div className="wizard-copy">
                Add annual care, bistro string lighting, or a night-mode
                preview. Leave any optional section blank and it stays out of
                the client proposal.
              </div>
            </div>
            <EnhancementsStep wizard={wizard} onOpenNight={onOpenNight} />
            <MiniTotals wizard={wizard} />
            <div className="wizard-nav">
              <button type="button" className="wizard-nav-btn secondary" onClick={goPrev}>
                Back
              </button>
              <button type="button" className="wizard-nav-btn primary" onClick={goNext}>
                Next: Review
              </button>
            </div>
          </section>

          {/* ── Step 5: Review ── */}
          <section className={`wizard-step${step === "review" ? " active" : ""}`}>
            <div className="wizard-step-heading">
              <div className="wizard-kicker">Step 5 of 5</div>
              <div className="wizard-title">
                <em>Review</em>{" "}&amp; Send
              </div>
              <div className="wizard-copy">
                Confirm the package totals, preview the client-facing
                proposal, then save it to get a shareable client link.
              </div>
            </div>

            <div className="wizard-review-intro">
              Package totals update live from your fixture counts and custom
              charges.
            </div>
            <div className="totals-panel">
              {order.map((key) => {
                const view = doc?.tiers.find((t) => t.key === key);
                const cfg = wizard.tierConfig(key);
                const hasValue = (view?.pricing.base ?? 0) > 0;
                return (
                  <div
                    key={key}
                    className={`total-card ${key}${hasValue ? " has-value" : ""}`}
                  >
                    <div className="total-card-tier">
                      {cfg?.card_tier ?? cfg?.tab ?? view?.label ?? key}
                    </div>
                    <div className="total-card-name">
                      {view?.name ?? cfg?.name ?? ""}
                    </div>
                    <div className="total-card-amount">
                      {hasValue ? fmt(view?.pricing.financed_total) : "—"}
                    </div>
                  </div>
                );
              })}
            </div>

            {commissionRate > 0 ? (
              <div className="commission-panel">
                <div className="commission-title">
                  Company-facing commission breakdown
                </div>
                <div className="commission-sub">
                  Internal only. Shows {ratePct}% commission by package;
                  cash/check uses the discounted client price, financed uses
                  the full quote total.
                  {pricing?.commission?.in_price
                    ? " Baked into every client price (back-end), so the payout is recovered from the customer and never touches margin."
                    : " Paid out of margin — not added to the client price."}
                </div>
                <div className="commission-grid">
                  {order.map((key) => {
                    const view = doc?.tiers.find((t) => t.key === key);
                    const hasValue = (view?.pricing.base ?? 0) > 0;
                    return (
                      <div className="commission-card" key={key}>
                        <div className="commission-card-title">
                          {view?.name ?? key}
                        </div>
                        <div className="commission-line">
                          <span>Full quote</span>
                          <strong>
                            {hasValue ? fmt(view?.pricing.financed_total) : "—"}
                          </strong>
                        </div>
                        <div className="commission-line cash">
                          <span>Cash/check {ratePct}%</span>
                          <strong>
                            {hasValue ? fmt(view?.pricing.commission_cash) : "—"}
                          </strong>
                        </div>
                        <div className="commission-line">
                          <span>Financed {ratePct}%</span>
                          <strong>
                            {hasValue
                              ? fmt(view?.pricing.commission_financed)
                              : "—"}
                          </strong>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            ) : null}

            <div className="rep-notes">
              <div className="rep-notes-title">
                &#9888; Rep Notes — Financing Fees (internal only)
              </div>
              <ul className="rep-notes-list">
                <li>
                  <strong>
                    All prices above already include the financing fee buffer.
                  </strong>{" "}
                  It&rsquo;s grossed into every fixture price and add-on
                  automatically, so a financed job&rsquo;s net survives the
                  dealer fee &mdash; for add-ons, enter the amount{" "}
                  <em>we keep</em>{" "}and the tool does the rest.
                </li>
                <li>
                  <strong>Financed customers pay 0% APR.</strong>{" "}The monthly
                  is just the total &divide; the chosen term &mdash; no
                  interest. We absorb the fee, not them.
                </li>
                <li>
                  <strong>
                    Cash/check keeps a private payment reserve.
                  </strong>{" "}
                  The tool backs out the financing buffer while leaving that
                  reserve in the client-facing cash/check price. Keep the fee
                  math internal.
                </li>
                <li>
                  <strong>Saving creates the quote at the financed total</strong>{" "}
                  &mdash; the client link leads with the cash/check price, and
                  both figures stay on the saved snapshot. Don&rsquo;t stack
                  another discount on top; that gives the margin away twice.
                </li>
                <li>
                  <strong>Financing cap applies.</strong>{" "}Above the cap, no
                  monthly figure is shown &mdash; split the financed portion
                  and take the rest as deposit.
                </li>
                <li>
                  <strong>
                    Bistro / patio string lighting follows the same rules.
                  </strong>{" "}
                  Its price carries the same private reserve and leads with
                  the clean cash/check price &mdash; exactly like the packages.
                </li>
              </ul>
            </div>

            <div className="action-row">
              <button type="button" className="present-btn" onClick={onPresent}>
                Preview Proposal
              </button>
              <button
                type="button"
                className="email-btn"
                disabled={wizard.isSaving}
                onClick={() => void handleSave()}
              >
                {wizard.isSaving ? "Saving…" : "\u2605 Save & Get Client Link"}
              </button>
            </div>

            {shareLink ? (
              <div className="share-link">
                <div className="share-link-label">Client proposal link</div>
                <div className="share-link-row">
                  <input
                    className="share-link-input"
                    readOnly
                    value={shareLink}
                    onFocus={(e) => e.currentTarget.select()}
                  />
                  <button
                    type="button"
                    className="share-link-copy"
                    onClick={() => void copyShareLink()}
                  >
                    Copy
                  </button>
                </div>
              </div>
            ) : null}

            <div className="wizard-nav">
              <button type="button" className="wizard-nav-btn secondary" onClick={goPrev}>
                Back to Add-ons
              </button>
              <span className="wizard-nav-spacer" />
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
