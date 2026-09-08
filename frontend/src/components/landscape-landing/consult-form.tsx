"use client";

import { useMutation } from "@tanstack/react-query";
import { AlertCircle, ArrowLeft, ArrowRight, CheckCircle2, Loader2, Phone } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { PhoneInput, normalizeToE164 } from "@/components/landing/phone-input";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { submitPublicLead, type PublicLeadSubmission } from "@/lib/api/public-leads";

const SCOPE_OPTIONS = [
  { value: "Front yard and entry", hint: "Curb appeal where guests arrive" },
  { value: "Whole property", hint: "Front, sides, back, and features" },
  { value: "Not sure yet", hint: "Walk me through the options" },
] as const;

const TIMELINE_OPTIONS = [
  "As soon as possible",
  "This season",
  "Next year",
  "Just exploring for now",
] as const;

const FIELD_CLASS =
  "h-12 border-white/15 bg-white/[0.06] text-white placeholder:text-zinc-500 focus-visible:border-brand-gold/60 focus-visible:ring-brand-gold/30";

const TRACKED_PARAMS = [
  "utm_source",
  "utm_medium",
  "utm_campaign",
  "utm_content",
  "utm_term",
  "gclid",
  "fbclid",
] as const;

// Ad platforms land a homeowner with these on the URL, but they often refresh,
// bookmark, or come back later from the same session with a bare URL. Holding
// first touch here keeps the lead credited to the ad that actually earned it.
// sessionStorage, not localStorage: attribution should not outlive the visit.
const ATTRIBUTION_KEY = "landscape-lighting:first-touch";

type TrackedParams = Partial<Record<(typeof TRACKED_PARAMS)[number], string>>;

/** Values are visitor-controlled, so cap every field to the backend's limit. */
function readParams(source: URLSearchParams | Record<string, unknown>): TrackedParams {
  const get = (key: string) =>
    source instanceof URLSearchParams ? source.get(key) : source[key];
  const params: TrackedParams = {};
  for (const key of TRACKED_PARAMS) {
    const value = get(key);
    if (typeof value === "string" && value.trim()) params[key] = value.slice(0, 255);
  }
  return params;
}

/**
 * Record the ad evidence on this URL as first touch, once per session.
 *
 * Storage is best-effort: Safari private mode and blocked-cookie setups throw
 * on access, and losing attribution must never cost the lead itself.
 */
function persistFirstTouch(): void {
  if (typeof window === "undefined") return;
  const current = readParams(new URLSearchParams(window.location.search));
  if (Object.keys(current).length === 0) return;
  try {
    if (window.sessionStorage.getItem(ATTRIBUTION_KEY)) return;
    window.sessionStorage.setItem(
      ATTRIBUTION_KEY,
      JSON.stringify({ ...current, referrer: document.referrer.slice(0, 2048) || undefined }),
    );
  } catch {
    // Storage unavailable: the current URL still carries attribution below.
  }
}

function readStoredFirstTouch(): TrackedParams & { referrer?: string } {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.sessionStorage.getItem(ATTRIBUTION_KEY);
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return {};
    const record = parsed as Record<string, unknown>;
    const referrer = record.referrer;
    return {
      ...readParams(record),
      referrer: typeof referrer === "string" ? referrer.slice(0, 2048) : undefined,
    };
  } catch {
    return {};
  }
}

/** UTM/click evidence for the CRM, preferring this URL and falling back to first touch. */
function readAttribution(): Partial<PublicLeadSubmission> {
  if (typeof window === "undefined") return {};
  const stored = readStoredFirstTouch();
  const current = readParams(new URLSearchParams(window.location.search));
  return {
    ...stored,
    ...current,
    landing_page: window.location.href.slice(0, 2048),
    referrer: document.referrer.slice(0, 2048) || stored.referrer,
  };
}

interface ConsultFormProps {
  /** Lead source public key. The page renders a call-us fallback when it is missing. */
  publicKey: string;
  businessPhone: string;
  businessPhoneHref: string;
}

export function ConsultForm({ publicKey, businessPhone, businessPhoneHref }: ConsultFormProps) {
  const [step, setStep] = useState(0);
  const [scope, setScope] = useState("");
  const [timeline, setTimeline] = useState("");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [address, setAddress] = useState("");
  const [smsConsent, setSmsConsent] = useState(false);
  const headingRef = useRef<HTMLHeadingElement>(null);

  // Capture the ad click on arrival, not at submit: the homeowner may refresh
  // or return with a clean URL before finishing the form.
  useEffect(persistFirstTouch, []);

  const mutation = useMutation({
    mutationFn: (body: PublicLeadSubmission) => submitPublicLead(publicKey, body),
  });

  // Move focus to the new step's heading so keyboard and screen-reader users
  // land on the question instead of the top of the document.
  const goToStep = (next: number) => {
    setStep(next);
    requestAnimationFrame(() => headingRef.current?.focus());
  };

  const isPhoneValid = normalizeToE164(phone).length >= 12;

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!firstName.trim() || !isPhoneValid || mutation.isPending) return;
    mutation.mutate(
      {
        first_name: firstName.trim(),
        last_name: lastName.trim() || undefined,
        phone_number: normalizeToE164(phone),
        email: email.trim() || undefined,
        address: address.trim() || undefined,
        notes: `Landscape lighting request\nScope: ${scope || "Not specified"}\nTimeline: ${timeline || "Not specified"}`,
        source_detail: "Landscape lighting landing page",
        sms_consent: smsConsent,
        ...readAttribution(),
      },
      { onSuccess: () => goToStep(3) },
    );
  };

  if (step === 3) {
    return (
      <div className="rounded-2xl border border-brand-gold/25 bg-white/[0.04] p-6 sm:p-8" aria-live="polite">
        <CheckCircle2 className="size-10 text-brand-gold" aria-hidden="true" />
        <h3 ref={headingRef} tabIndex={-1} className="mt-4 text-2xl font-semibold text-white outline-none">
          Your consultation request is in
        </h3>
        <p className="mt-2 text-zinc-300">
          We will text you shortly to confirm a time that works. Prefer to talk right now?
        </p>
        <Button asChild size="lg" className="mt-6 h-12 bg-brand-gold font-semibold text-zinc-950 hover:bg-brand-gold-bright">
          <a href={businessPhoneHref}>
            <Phone className="size-4" aria-hidden="true" />
            Call {businessPhone}
          </a>
        </Button>
      </div>
    );
  }

  return (
    <div className="rounded-2xl border border-white/12 bg-white/[0.04] p-6 sm:p-8">
      <p className="text-xs font-semibold uppercase tracking-widest text-brand-gold/90">Step {step + 1} of 3</p>

      {step === 0 && (
        <fieldset className="mt-4">
          <legend className="sr-only">What would you like to light?</legend>
          <h3 ref={headingRef} tabIndex={-1} className="text-2xl font-semibold text-white outline-none">
            What would you like to light?
          </h3>
          <p className="mt-2 text-zinc-300">A quick answer lets us plan the right consultation for your property.</p>
          <div className="mt-6 space-y-3">
            {SCOPE_OPTIONS.map((option) => (
              <button
                key={option.value}
                type="button"
                onClick={() => {
                  setScope(option.value);
                  goToStep(1);
                }}
                className="flex w-full items-center justify-between gap-4 rounded-xl border border-white/12 bg-white/[0.03] px-4 py-4 text-left transition-colors duration-150 hover:border-brand-gold/50 hover:bg-white/[0.07] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-gold"
              >
                <span>
                  <span className="block font-medium text-white">{option.value}</span>
                  <span className="mt-0.5 block text-sm text-zinc-400">{option.hint}</span>
                </span>
                <ArrowRight className="size-4 shrink-0 text-brand-gold" aria-hidden="true" />
              </button>
            ))}
          </div>
        </fieldset>
      )}

      {step === 1 && (
        <fieldset className="mt-4">
          <legend className="sr-only">When are you thinking about installation?</legend>
          <h3 ref={headingRef} tabIndex={-1} className="text-2xl font-semibold text-white outline-none">
            When are you thinking about installation?
          </h3>
          <p className="mt-2 text-zinc-300">This tells us how much of the calendar to hold for you.</p>
          <div className="mt-6 space-y-3">
            {TIMELINE_OPTIONS.map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => {
                  setTimeline(option);
                  goToStep(2);
                }}
                className="flex w-full items-center justify-between gap-4 rounded-xl border border-white/12 bg-white/[0.03] px-4 py-4 text-left font-medium text-white transition-colors duration-150 hover:border-brand-gold/50 hover:bg-white/[0.07] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-gold"
              >
                {option}
                <ArrowRight className="size-4 shrink-0 text-brand-gold" aria-hidden="true" />
              </button>
            ))}
          </div>
          <BackButton onClick={() => goToStep(0)} />
        </fieldset>
      )}

      {step === 2 && (
        <form className="mt-4" onSubmit={handleSubmit} noValidate>
          <h3 ref={headingRef} tabIndex={-1} className="text-2xl font-semibold text-white outline-none">
            Where should we reach you?
          </h3>
          <p className="mt-2 text-zinc-300">
            We will text you to confirm a time for your design consultation. No obligation.
          </p>

          <div className="mt-6 grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="lead-first-name" className="text-zinc-200">
                First name <span className="text-brand-gold">*</span>
              </Label>
              <Input
                id="lead-first-name"
                value={firstName}
                onChange={(event) => setFirstName(event.target.value)}
                autoComplete="given-name"
                required
                maxLength={100}
                className={FIELD_CLASS}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="lead-last-name" className="text-zinc-200">
                Last name
              </Label>
              <Input
                id="lead-last-name"
                value={lastName}
                onChange={(event) => setLastName(event.target.value)}
                autoComplete="family-name"
                maxLength={100}
                className={FIELD_CLASS}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="lead-phone" className="text-zinc-200">
                Mobile number <span className="text-brand-gold">*</span>
              </Label>
              <PhoneInput
                id="lead-phone"
                value={phone}
                onChange={setPhone}
                required
                className={`${FIELD_CLASS} font-mono`}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="lead-email" className="text-zinc-200">
                Email
              </Label>
              <Input
                id="lead-email"
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                autoComplete="email"
                className={FIELD_CLASS}
              />
            </div>
            <div className="space-y-2 sm:col-span-2">
              <Label htmlFor="lead-address" className="text-zinc-200">
                Property address
              </Label>
              <Input
                id="lead-address"
                value={address}
                onChange={(event) => setAddress(event.target.value)}
                autoComplete="street-address"
                maxLength={500}
                placeholder="Street, city, ZIP"
                className={FIELD_CLASS}
              />
            </div>
          </div>

          {/* 10DLC/TCR: optional and unchecked by default. Submitting never depends on it. */}
          <div className="mt-5 flex items-start gap-3">
            <Checkbox
              id="lead-sms-consent"
              checked={smsConsent}
              onCheckedChange={(checked) => setSmsConsent(checked === true)}
              className="mt-0.5 border-white/30 data-[state=checked]:border-brand-gold data-[state=checked]:bg-brand-gold data-[state=checked]:text-zinc-950"
            />
            <Label htmlFor="lead-sms-consent" className="text-sm font-normal leading-snug text-zinc-400">
              Text me about my design consultation and quote. Message and data rates may apply. Reply STOP to opt out.
            </Label>
          </div>

          {mutation.isError && (
            <Alert variant="destructive" role="alert" className="mt-5">
              <AlertCircle className="size-4" aria-hidden="true" />
              <AlertDescription>
                {(mutation.error as Error)?.message} You can also call {businessPhone}.
              </AlertDescription>
            </Alert>
          )}

          <Button
            type="submit"
            size="lg"
            disabled={!firstName.trim() || !isPhoneValid || mutation.isPending}
            className="mt-6 h-12 w-full bg-brand-gold font-semibold text-zinc-950 hover:bg-brand-gold-bright"
          >
            {mutation.isPending ? (
              <>
                <Loader2 className="size-4 animate-spin" aria-hidden="true" />
                Sending
              </>
            ) : (
              <>
                Request my design consultation
                <ArrowRight className="size-4" aria-hidden="true" />
              </>
            )}
          </Button>
          <BackButton onClick={() => goToStep(1)} />
        </form>
      )}
    </div>
  );
}

function BackButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="mt-5 inline-flex items-center gap-1.5 text-sm text-zinc-400 transition-colors duration-150 hover:text-brand-gold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-gold"
    >
      <ArrowLeft className="size-4" aria-hidden="true" />
      Go back
    </button>
  );
}
