"use client";

/**
 * The unified Quote Builder — a category-driven operator flow: Client → Product
 * Lines → (Design · Seasonal · Add-ons for the selected lines) → Review.
 * The rep picks which product lines the quote covers; only the relevant sections
 * render. Every price comes from the server preview document; the review step
 * shows one combined all-in total across every selected line.
 */
import { useId, useMemo, useState } from "react";
import { toast } from "sonner";

import { AttachPrompt, useAttachPromptActions } from "./attach-prompt";
import {
  ChristmasSection,
  GrandTotals,
  PermanentSection,
} from "./builder-sections";
import { CategoryStep, SERVICE_ACCENTS } from "./category-step";
import { ClientTypeahead } from "./client-typeahead";
import { DesignStep, MiniTotals } from "./design-step";
import { EnhancementsStep, MockupsBlock } from "./enhancements-step";
import { PresentationScreen } from "./presentation-screen";
import { fmt, type ClientDraft, type UseSalesWizardReturn } from "./use-sales-wizard";

/**
 * The quote-builder flow: capture the customer, show them the vision, price the
 * work, preview what they will receive, then send it.
 *
 * Kept in sync with the `steps` array in `CalculatorScreen` — the sections read
 * their visibility from that array rather than comparing hardcoded strings, so
 * a rename here is a type error instead of an invisible step.
 */
export type WizardStepId =
  | "customer"
  | "mockup"
  | "lines"
  | "preview"
  | "send";

interface StepDef {
  id: WizardStepId;
  label: string;
}

interface CalculatorScreenProps {
  wizard: UseSalesWizardReturn;
  brandName: string;
  onOpenNight: () => void;
}

interface FieldProps {
  wizard: UseSalesWizardReturn;
  field: keyof ClientDraft;
  label: string;
  placeholder: string;
  type?: string;
}

/** Small accent pill naming the service a builder step belongs to. */
function ServiceTag({ label, accent }: { label: string; accent: string }) {
  return (
    <span
      className="wizard-service-tag"
      style={{ "--svc-accent": accent } as React.CSSProperties}
    >
      {label}
    </span>
  );
}

function ClientField({ wizard, field, label, placeholder, type }: FieldProps) {
  const inputId = useId();
  return (
    <div className="field-wrap">
      <label className="field-label" htmlFor={inputId}>
        {label}
      </label>
      <input
        id={inputId}
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

/**
 * Client name field with typeahead over the workspace's existing customers.
 * Taking a suggestion fills the rest of the block and files the quote on that
 * record; typing straight through creates a new client, as before.
 */
function ClientNameField({ wizard, field, label, placeholder }: FieldProps) {
  return (
    <ClientTypeahead
      workspaceId={wizard.workspaceId}
      label={label}
      placeholder={placeholder}
      value={wizard.client[field]}
      onValueChange={(value) => wizard.setClientField(field, value)}
      onPickContact={wizard.applyContact}
    />
  );
}

/** Shows which saved customer the quote is filed against, with a way out. */
function LinkedClientChip({ wizard }: { wizard: UseSalesWizardReturn }) {
  const name =
    [wizard.client.first_name, wizard.client.last_name]
      .filter(Boolean)
      .join(" ")
      .trim() || "this client";
  return (
    <div className="client-link-chip">
      <span className="client-link-chip-text">Existing client · {name}</span>
      <button
        type="button"
        onClick={wizard.clearLinkedContact}
        aria-label={`Unlink ${name} and save this quote under a new client`}
      >
        Unlink
      </button>
    </div>
  );
}

/**
 * Upfront deposit control for the Review step. The rep picks percentage or a
 * fixed amount; leaving it blank inherits the workspace default on save. The
 * resolved amount due comes from the server document so it always matches what
 * the client is charged.
 */
function DepositField({ wizard }: { wizard: UseSalesWizardReturn }) {
  const { depositMode, setDepositMode, depositInput, setDepositInput } = wizard;
  const configured = wizard.pricing?.deposit;
  const resolved = wizard.document?.deposit_amount ?? 0;
  const hasValue = Number.parseFloat(depositInput) > 0;
  const defaultHint =
    configured?.enabled && (configured.value ?? 0) > 0
      ? configured.mode === "fixed"
        ? `Default: ${fmt(configured.value)}`
        : `Default: ${configured.value}%`
      : "No default set";
  return (
    <div className="deposit-field">
      <div className="deposit-field-head">
        <div className="deposit-field-title">Upfront Deposit</div>
        <div className="deposit-field-hint">{defaultHint}</div>
      </div>
      <div className="deposit-field-row">
        <div className="deposit-mode-toggle" role="group" aria-label="Deposit mode">
          <button
            type="button"
            className={depositMode === "percentage" ? "active" : ""}
            onClick={() => setDepositMode("percentage")}
          >
            %
          </button>
          <button
            type="button"
            className={depositMode === "fixed" ? "active" : ""}
            onClick={() => setDepositMode("fixed")}
          >
            $
          </button>
        </div>
        <input
          className="deposit-input"
          type="number"
          min={0}
          step={depositMode === "percentage" ? 5 : 50}
          inputMode="decimal"
          placeholder={depositMode === "percentage" ? "e.g. 50" : "e.g. 1000"}
          value={depositInput}
          onChange={(e) => setDepositInput(e.target.value)}
          aria-label="Deposit value"
        />
        <div className="deposit-due">
          {resolved > 0 ? (
            <>
              <span className="deposit-due-amount">{fmt(resolved)}</span>
              <span className="deposit-due-label">due at acceptance</span>
            </>
          ) : (
            <span className="deposit-due-label">
              {hasValue ? "Add lines to price the deposit" : "No deposit"}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

export function CalculatorScreen({
  wizard,
  brandName,
  onOpenNight,
}: CalculatorScreenProps) {
  const { document: doc, pricing } = wizard;
  const hasLandscape = wizard.hasCategory("landscape");
  const hasSeasonal =
    wizard.hasCategory("permanent") || wizard.hasCategory("christmas");
  // Permanent and Christmas are separate services that happen to share one step
  // (`id: "seasonal"`, kept so step ordering is untouched). Its label, heading,
  // and service tag follow the active service, so a permanent quote is never
  // presented as Christmas.
  const isPermanentService = wizard.activeService === "permanent";
  // Roofline work (permanent track or seasonal Christmas) is measured on the
  // photo; landscape work is placed fixture by fixture. The Mockup step says
  // which, so the rep knows what the designer is for on this quote.
  const isSeasonalService = isPermanentService || hasSeasonal;
  const seasonalStep = isPermanentService
    ? {
        // The progress chip clips past ~8 tracked characters, so the step reads
        // "Roofline" (what this step prices) while the tag names the service.
        label: "Roofline",
        tag: "Holiday Lights \u2014 Permanent",
        accent: SERVICE_ACCENTS.permanent,
        copy:
          "Price the year-round LED roofline track. Enter footage and zones \u2014 " +
          "every line prices live off your workspace rates.",
      }
    : {
        label: "Seasonal",
        tag: "Christmas & Holiday Lighting",
        accent: SERVICE_ACCENTS.christmas,
        copy:
          "Price this season's Christmas lighting. Enter roofline footage and " +
          "decor counts \u2014 every line prices live off your workspace rates.",
      };

  // The rep's five moves, in the order a quote is actually sold: capture who
  // it is for, show them what it will look like, price it, look at what they
  // will see, then send it.
  //
  // Every step here is unconditional. The product lines a quote covers vary, so
  // they vary *inside* Line Items rather than adding and removing steps beneath
  // the rep: a progress bar whose length changes when you tick a checkbox
  // renumbers the step you are standing on.
  const steps = useMemo<StepDef[]>(
    () => [
      { id: "customer", label: "Customer" },
      { id: "mockup", label: "Mockup" },
      { id: "lines", label: "Line Items" },
      { id: "preview", label: "Preview" },
      { id: "send", label: "Send" },
    ],
    [],
  );

  const [stepState, setStep] = useState<WizardStepId>("customer");
  const step = steps.some((s) => s.id === stepState) ? stepState : "customer";
  const stepIndex = Math.max(
    0,
    steps.findIndex((s) => s.id === step),
  );
  const stepOf = (id: WizardStepId) => {
    const i = steps.findIndex((s) => s.id === id);
    return `Step ${i + 1} of ${steps.length}`;
  };
  /** Section visibility, derived from the step list so a rename cannot silently
   * hide a whole step's UI the way six hardcoded string comparisons could. */
  const on = (id: WizardStepId) => `wizard-step${step === id ? " active" : ""}`;

  const goTo = (id: WizardStepId) => {
    setStep(id);
    window.scrollTo(0, 0);
  };
  const goNext = () =>
    goTo(steps[Math.min(stepIndex + 1, steps.length - 1)].id);
  const goPrev = () => goTo(steps[Math.max(stepIndex - 1, 0)].id);

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

  const attach = useAttachPromptActions(wizard);

  const handleSave = async () => {
    try {
      const quote = await wizard.save();
      toast.success("Proposal saved — client link ready");
      return quote;
    } catch (err) {
      // A blocking attach rule is not a failure to retry blindly: the prompt
      // beside the button says exactly what to add or skip.
      toast.error(attach.saveErrorMessage(err));
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

  const handleDeliver = async (channel: "email" | "sms") => {
    try {
      const result = await wizard.deliver(channel);
      toast.success(
        channel === "email"
          ? `Proposal emailed to ${result.to}`
          : `Proposal texted to ${result.to}`,
      );
    } catch (err) {
      const data = (
        err as { response?: { data?: { message?: unknown; detail?: unknown } } }
      )?.response?.data;
      const message =
        typeof data?.message === "string"
          ? data.message
          : typeof data?.detail === "string"
            ? data.detail
            : null;
      toast.error(
        message ??
          (channel === "email"
            ? "Could not email the proposal."
            : "Could not text the proposal."),
      );
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
            <em>Quote</em>{" "}Builder
          </div>
          <div className="calc-rule" />
          <div className="calc-sub">
            Build the quote, price every line, then preview or send
          </div>
        </div>

        <div
          className="wizard-progress"
          aria-label="Quote builder progress"
          style={{
            gridTemplateColumns: `repeat(${steps.length}, 1fr)`,
          }}
        >
          {steps.map((s, i) => (
            <button
              key={s.id}
              type="button"
              className={`wizard-progress-btn${s.id === step ? " active" : ""}${i < stepIndex ? " done" : ""}`}
              aria-current={s.id === step ? "step" : "false"}
              onClick={() => goTo(s.id)}
            >
              <span className="wizard-step-num">
                {String(i + 1).padStart(2, "0")}
              </span>
              <span className="wizard-step-label">{s.label}</span>
            </button>
          ))}
        </div>

        <div className="wizard-shell">
          {/* ── 1 · Customer ── */}
          <section className={on("customer")}>
            <div className="wizard-step-heading">
              <div className="wizard-kicker">{stepOf("customer")}</div>
              <div className="wizard-title">
                <em>Customer</em>{" "}Details
              </div>
              <div className="wizard-copy">
                Capture the client, property, and rep info once. These fields
                feed the proposal and the saved quote.
              </div>
            </div>
            <div className="fields-block">
              <div className="fields-block-head">
                <div className="fields-block-label">Client Information</div>
                {wizard.linkedContactId !== null ? (
                  <LinkedClientChip wizard={wizard} />
                ) : null}
              </div>
              <div className="fields-grid-2">
                <ClientNameField wizard={wizard} field="first_name" label="First Name" placeholder="Sarah" />
                <ClientNameField wizard={wizard} field="last_name" label="Last Name" placeholder="Henderson" />
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
                Next: Mockup
              </button>
            </div>
          </section>

          {/* ── 2 · Mockup ──
              Every visual the client will see, in one place: the lit-photo
              designer and the uploaded mockup gallery. Deliberately ungated ──
              it used to sit inside the landscape-only Design step, which left
              a Christmas rep with no way to reach the Light Designer at all,
              even though saving one already feeds roofline feet back into a
              Christmas quote. */}
          <section className={on("mockup")}>
            <div className="wizard-step-heading">
              <div className="wizard-kicker">{stepOf("mockup")}</div>
              <div className="wizard-title">
                <em>Visual</em>{" "}Mockup
              </div>
              <div className="wizard-copy">
                Show them the house before you price it. Light a photo of the
                property, or upload mockups. Both ride along to the client
                proposal.
              </div>
            </div>
            <button
              type="button"
              className={`night-launch-btn${wizard.night.image ? " saved" : ""}`}
              onClick={onOpenNight}
            >
              {wizard.night.image
                ? "Design saved \u2014 edit the lit photo"
                : "Open the Light Designer"}
            </button>
            <div className="night-launch-sub">
              {wizard.night.image
                ? "Saved to this proposal \u2014 it shows on the client’s shared page and the quote is filed on their customer record."
                : isSeasonalService
                  ? "Trace the rooflines and place decor on a photo of the home, then drag dusk down to show it lit. Saving pushes the measured roofline feet into this quote and files the image with the proposal."
                  : "Place uplights, spots, path lights and wall washes on a photo of the home, then drag dusk down to show it lit. Saving pushes the fixture counts into this quote and files the image with the proposal."}
            </div>
            <MockupsBlock wizard={wizard} />
            <div className="wizard-nav">
              <button type="button" className="wizard-nav-btn secondary" onClick={goPrev}>
                Back
              </button>
              <button type="button" className="wizard-nav-btn primary" onClick={goNext}>
                Next: Line Items
              </button>
            </div>
          </section>

          {/* ── 3 · Line Items ──
              One step, priced top to bottom: what the quote covers, then the
              per-service lines for whichever product lines it covers, then the
              optional add-ons. The sub-sections vary by service; the step does
              not. */}
          <section className={on("lines")}>
            <div className="wizard-step-heading">
              <div className="wizard-kicker">{stepOf("lines")}</div>
              <div className="wizard-title">
                <em>Line</em>{" "}Items
              </div>
              <div className="wizard-copy">
                Pick the service this quote covers, then price every line. One
                quote, one service — switching services starts that
                service&apos;s quote.
              </div>
            </div>
            <CategoryStep wizard={wizard} />

            {/* ── Landscape packages ── */}
            {hasLandscape ? (
              <div className="wizard-substep">
                <ServiceTag
                  label="Landscape Lighting"
                  accent={SERVICE_ACCENTS.landscape}
                />
                <div className="wizard-title">
                  <em>Design</em>{" "}Packages
                </div>
                <div className="wizard-copy">
                  Build Good / Better / Best options with fixture counts. Add any
                  custom job charges here so every package total stays accurate.
                </div>
                <DesignStep wizard={wizard} />
              </div>
            ) : null}


            {/* ── Seasonal / permanent roofline ── */}
            {hasSeasonal ? (
              <div className="wizard-substep">
                <ServiceTag
                  label={seasonalStep.tag}
                  accent={seasonalStep.accent}
                />
                <div className="wizard-title">
                  {isPermanentService ? (
                    <>
                      <em>Permanent</em>{" "}Roofline
                    </>
                  ) : (
                    <>
                      <em>Seasonal</em>{" "}Christmas
                    </>
                  )}
                </div>
                <div className="wizard-copy">{seasonalStep.copy}</div>
                <div className="wizard-copy">{seasonalStep.copy}</div>
                {wizard.hasCategory("permanent") ? (
                  <PermanentSection wizard={wizard} />
                ) : null}
                {wizard.hasCategory("christmas") ? (
                  <ChristmasSection wizard={wizard} />
                ) : null}
              </div>
            ) : null}

            {/* ── Optional add-ons (each gates itself on its product line) ── */}
            <div className="wizard-substep">
              <div className="wizard-title">
                <em>Add</em>{" "}Ons
              </div>
              <div className="wizard-copy">
                Annual care and bistro string lighting. Leave a section blank
                and it stays out of the client proposal.
              </div>
            </div>
            <EnhancementsStep wizard={wizard} />
            {hasLandscape ? <MiniTotals wizard={wizard} /> : null}

            {/* The priced result of everything above. Totals live with the
                inputs that move them, so a rep never has to leave the step to
                find out what a change did. */}

            <div className="wizard-review-intro">
              Totals update live from your inputs across every selected product
              line.
            </div>

            <GrandTotals wizard={wizard} />

            <DepositField wizard={wizard} />

            {hasLandscape ? (
              <div className="totals-panel" style={{ marginTop: 16 }}>
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
            ) : null}

            {hasLandscape && commissionRate > 0 ? (
              <div className="commission-panel">
                <div className="commission-title">
                  Company-facing commission breakdown
                </div>
                <div className="commission-sub">
                  Internal only. Shows {ratePct}% commission by package;
                  cash/check uses the discounted client price, financed uses the
                  full quote total.
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
                &#9888; Rep Notes — Pricing (internal only)
              </div>
              <ul className="rep-notes-list">
                <li>
                  <strong>Financing is category-qualified.</strong>{" "}Only
                  quote a monthly estimate when this builder shows one; workspace
                  minimums intentionally suppress low-value jobs. It is never an
                  approval or guarantee, and the client sees the disclaimer with
                  every estimate.
                </li>
                <li>
                  <strong>Prices still carry the pricing buffer.</strong>{" "}
                  It&rsquo;s grossed into every price and add-on automatically —
                  for add-ons, enter the amount <em>we keep</em> and the tool
                  does the rest. That buffer is margin protection, never
                  something to describe to the client.
                </li>
                <li>
                  <strong>Cash/check keeps a private payment reserve.</strong>{" "}
                  The tool backs the buffer out while leaving that reserve in the
                  cash/check figure. Keep the fee math internal.
                </li>
                <li>
                  <strong>Saving creates the quote at the all-in total</strong>{" "}
                  — both figures stay on the saved snapshot. Don&rsquo;t stack
                  another discount on top; that gives the margin away twice.
                </li>
              </ul>
            </div>

            <div className="wizard-nav">
              <button type="button" className="wizard-nav-btn secondary" onClick={goPrev}>
                Back
              </button>
              <button type="button" className="wizard-nav-btn primary" onClick={goNext}>
                Next: Preview
              </button>
            </div>
          </section>

          {/* ── 4 · Preview ──
              The client's page, rendered from the same server document they
              will be sent. Shown in place rather than as a separate screen so
              the rep can step back to Line Items and forward to Send without
              losing the flow. */}
          <section className={on("preview")}>
            <div className="wizard-step-heading">
              <div className="wizard-kicker">{stepOf("preview")}</div>
              <div className="wizard-title">
                <em>Preview</em>{" "}the Proposal
              </div>
              <div className="wizard-copy">
                Exactly what the customer opens. Check the name, the totals,
                and the mockups before you send it.
              </div>
            </div>
            <PresentationScreen wizard={wizard} brandName={brandName} />
            <div className="wizard-nav">
              <button type="button" className="wizard-nav-btn secondary" onClick={goPrev}>
                Back
              </button>
              <button type="button" className="wizard-nav-btn primary" onClick={goNext}>
                Next: Send
              </button>
            </div>
          </section>

          {/* ── 5 · Send ── */}
          <section className={on("send")}>
            <div className="wizard-step-heading">
              <div className="wizard-kicker">{stepOf("send")}</div>
              <div className="wizard-title">
                <em>Send</em>{" "}to the Customer
              </div>
              <div className="wizard-copy">
                Save the quote to mint the client link, then text or email it.
                Both go to the details captured in step 1.
              </div>
            </div>

            {wizard.attachWarning && (
              <AttachPrompt
                warning={wizard.attachWarning}
                busy={wizard.isSaving}
                onAdd={attach.add}
                onDismiss={attach.dismiss}
              />
            )}

            <div className="action-row">
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
                <div className="share-link-row">
                  <button
                    type="button"
                    className="share-send-btn"
                    disabled={wizard.isDelivering || !wizard.client.email}
                    title={
                      wizard.client.email
                        ? undefined
                        : "Add a customer email in step 1"
                    }
                    onClick={() => void handleDeliver("email")}
                  >
                    {wizard.isDelivering
                      ? "Sending…"
                      : `✉ Email to ${wizard.client.email || "client"}`}
                  </button>
                  <button
                    type="button"
                    className="share-send-btn"
                    disabled={wizard.isDelivering || !wizard.client.phone}
                    title={
                      wizard.client.phone
                        ? undefined
                        : "Add a customer phone in step 1"
                    }
                    onClick={() => void handleDeliver("sms")}
                  >
                    {wizard.isDelivering
                      ? "Sending…"
                      : `☎ Text to ${wizard.client.phone || "client"}`}
                  </button>
                </div>
              </div>
            ) : null}

            <div className="wizard-nav">
              <button type="button" className="wizard-nav-btn secondary" onClick={goPrev}>
                Back
              </button>
              <span className="wizard-nav-spacer" />
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
