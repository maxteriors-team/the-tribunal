"use client";

import { ClipboardCheck } from "lucide-react";
import { useMemo } from "react";
import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { CreateSMSCampaignRequest } from "@/lib/api/sms-campaigns";
import {
  formatAmountTerm,
  nextSeasonYear,
  previewOffer,
  resolveSeasonWindow,
} from "@/lib/pre-booking";
import { formatLongDate } from "@/lib/utils/date";
import { formatCurrency } from "@/lib/utils/number";
import type { Agent, Offer, PhoneNumber, PreBookingConfigCreate } from "@/types";

import {
  type BasicsFields,
  type ScheduleFields,
  initialBasicsFields,
  initialScheduleFields,
  makeBasicsStep,
  mapScheduleToRequest,
} from "./_shared";
import { BaseCampaignWizard } from "./base-campaign-wizard";
import {
  type AudienceStepFields,
  type LaunchStepFields,
  type OfferStepFields,
  type SeasonStepFields,
  LeadTimeCallout,
  makeAudienceStep,
  makeLaunchStep,
  makeOfferStep,
  makeSeasonStep,
  resolveLeadTime,
} from "./pre-booking-steps";
import {
  type AgentStepFields,
  type MessageStepFields,
  makeAgentStep,
  makeMessageStep,
} from "./sms-steps";
import type { WizardStep } from "./wizard-types";

type StepId =
  | "basics"
  | "season"
  | "offer"
  | "audience"
  | "message"
  | "agent"
  | "launch"
  | "review";

/**
 * Everything the wizard collects. A pre-booking campaign is an ordinary SMS
 * campaign (`BasicsFields` + `MessageStepFields` + `AgentStepFields` +
 * `ScheduleFields`) plus the offer that makes it a pre-booking one — so the
 * delivery half of this form is literally the builders the SMS wizard uses.
 */
export interface PreBookingFormData
  extends BasicsFields,
    ScheduleFields,
    MessageStepFields,
    AgentStepFields,
    SeasonStepFields,
    OfferStepFields,
    AudienceStepFields,
    LaunchStepFields {
  messages_per_minute: number;
}

/** What the host page needs to create the campaign, offer, audience and launch. */
export interface PreBookingSubmission {
  campaign: CreateSMSCampaignRequest;
  offer: PreBookingConfigCreate;
  audience: {
    include_past_customers: boolean;
    include_unsold_quotes: boolean;
    include_prior_season_christmas: boolean;
  };
  /** ISO instant, or null when the operator chose to start immediately. */
  scheduledStart: string | null;
}

/**
 * Build the API payloads from the wizard's form state.
 *
 * Exported so the mapping is unit-testable without rendering eight steps. The
 * offer half matters most: the backend schema forbids unknown fields, and
 * `example_job_amount` is wizard-only scratch that must never be sent.
 */
export function buildPreBookingSubmission(
  formData: PreBookingFormData,
): PreBookingSubmission {
  return {
    campaign: {
      name: formData.name,
      description: formData.description || undefined,
      from_phone_number: formData.from_phone_number,
      initial_message: formData.initial_message,
      agent_id: formData.agent_id,
      offer_id: formData.offer_id,
      ai_enabled: formData.ai_enabled,
      qualification_criteria: formData.qualification_criteria || undefined,
      ...mapScheduleToRequest(formData),
      messages_per_minute: formData.messages_per_minute,
      follow_up_enabled: formData.follow_up_enabled,
      follow_up_delay_hours: formData.follow_up_delay_hours,
      follow_up_message: formData.follow_up_message || undefined,
      max_follow_ups: formData.max_follow_ups,
    },
    offer: {
      service_season_start_month: formData.service_season_start_month,
      service_season_end_month: formData.service_season_end_month,
      service_season_year: formData.service_season_year,
      service_description: formData.service_description.trim(),
      incentive_type: formData.incentive_type,
      incentive_value: formData.incentive_value,
      deposit_type: formData.deposit_type,
      deposit_value: formData.deposit_value,
      slot_cap: formData.slot_cap,
      hold_hours: formData.hold_hours,
    },
    audience: {
      include_past_customers: formData.include_past_customers,
      include_unsold_quotes: formData.include_unsold_quotes,
      include_prior_season_christmas: formData.include_prior_season_christmas,
    },
    // `scheduled_start` doubles as the campaign's launch date, so an immediate
    // start deliberately sends nothing to the launch endpoint.
    scheduledStart:
      formData.start_immediately || !formData.scheduled_start
        ? null
        : new Date(formData.scheduled_start).toISOString(),
  };
}

/** Wizard defaults: the spring window a Michigan exteriors business lives on. */
export function buildInitialPreBookingFormData(
  today: Date = new Date(),
): PreBookingFormData {
  const startMonth = 3;
  return {
    ...initialBasicsFields,
    ...initialScheduleFields,
    initial_message: "",
    agent_id: undefined,
    offer_id: undefined,
    ai_enabled: true,
    qualification_criteria: "",
    follow_up_enabled: false,
    follow_up_delay_hours: 24,
    follow_up_message: "",
    max_follow_ups: 2,
    messages_per_minute: 10,
    service_season_start_month: startMonth,
    service_season_end_month: 5,
    // Never this year's spring if this year's spring has already started.
    service_season_year: nextSeasonYear({ startMonth, today }),
    service_description: "",
    incentive_type: "percentage",
    incentive_value: 15,
    deposit_type: "percentage",
    deposit_value: 25,
    slot_cap: 20,
    hold_hours: 72,
    example_job_amount: 450,
    include_past_customers: true,
    include_unsold_quotes: true,
    // Off by default: last season's lighting customers are a deliberate renewal
    // push, not a slice to widen the default audience with.
    include_prior_season_christmas: false,
    scheduled_start: undefined,
    start_immediately: false,
  };
}

interface PreBookingCampaignWizardProps {
  workspaceId: string;
  agents: Agent[];
  offers: Offer[];
  phoneNumbers: PhoneNumber[];
  onSubmit: (submission: PreBookingSubmission) => Promise<void>;
  onCreateOffer?: (offer: Partial<Offer>) => Promise<void>;
  onCancel?: () => void;
  isSubmitting?: boolean;
}

export function PreBookingCampaignWizard({
  workspaceId,
  agents,
  offers,
  phoneNumbers,
  onSubmit,
  onCreateOffer,
  onCancel,
  isSubmitting = false,
}: PreBookingCampaignWizardProps) {
  const steps = useMemo<ReadonlyArray<WizardStep<StepId, PreBookingFormData>>>(
    () => [
      makeBasicsStep<StepId, PreBookingFormData>({
        id: "basics",
        phoneNumbers,
        namePlaceholder: "e.g., Spring 2027 Pre-Book",
        emptyPhoneLabel: "No SMS or iMessage sender identities available",
      }),
      makeSeasonStep<StepId, PreBookingFormData>({ id: "season" }),
      makeOfferStep<StepId, PreBookingFormData>({ id: "offer" }),
      makeAudienceStep<StepId, PreBookingFormData>({
        id: "audience",
        workspaceId,
      }),
      makeMessageStep<StepId, PreBookingFormData>({
        id: "message",
        offers,
        onCreateOffer,
      }),
      makeAgentStep<StepId, PreBookingFormData>({ id: "agent", agents }),
      makeLaunchStep<StepId, PreBookingFormData>({ id: "launch" }),
      {
        id: "review",
        label: "Review",
        icon: ClipboardCheck,
        render: ({ formData }) => <ReviewStep formData={formData} />,
      },
    ],
    [agents, offers, onCreateOffer, phoneNumbers, workspaceId],
  );

  return (
    <BaseCampaignWizard
      steps={steps}
      initialFormData={buildInitialPreBookingFormData()}
      onSubmit={(formData) => onSubmit(buildPreBookingSubmission(formData))}
      isSubmitting={isSubmitting}
      onCancel={onCancel}
      submitLabel="Create Pre-Booking Campaign"
    />
  );
}

/**
 * Review: the offer as the customer will experience it, and the runway as the
 * calendar will. Bespoke rather than `makeReviewStep` because what is worth
 * checking twice here is not the sending window — it is the money and the date.
 */
function ReviewStep({ formData }: { formData: PreBookingFormData }) {
  const season = resolveSeasonWindow({
    startMonth: formData.service_season_start_month,
    endMonth: formData.service_season_end_month,
    year: formData.service_season_year,
  });
  const example = previewOffer({
    baseAmount: formData.example_job_amount,
    incentiveType: formData.incentive_type,
    incentiveValue: formData.incentive_value,
    depositType: formData.deposit_type,
    depositValue: formData.deposit_value,
  });
  const sources =
    [
      formData.include_past_customers ? "past customers" : null,
      formData.include_unsold_quotes ? "unsold quotes" : null,
      formData.include_prior_season_christmas
        ? "last season's holiday-lighting customers"
        : null,
    ]
      .filter(Boolean)
      .join(" + ") || "—";

  return (
    <div className="space-y-6">
      <LeadTimeCallout
        leadTime={resolveLeadTime(formData)}
        seasonLabel={season.label}
        seasonStart={season.start}
      />

      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            {formData.name || "Untitled campaign"}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <ReviewRow label="Selling">
            {formData.service_description || "—"}
          </ReviewRow>
          <ReviewRow label="Work happens">
            {season.label} ({formatLongDate(season.start)} –{" "}
            {formatLongDate(season.end)})
          </ReviewRow>
          <ReviewRow label="Offer">
            {formatAmountTerm(formData.incentive_type, formData.incentive_value)}{" "}
            off, {formatAmountTerm(formData.deposit_type, formData.deposit_value)}{" "}
            deposit to hold a slot
          </ReviewRow>
          <ReviewRow label="Slots">
            {formData.slot_cap} · unpaid holds expire after {formData.hold_hours}h
          </ReviewRow>
          <ReviewRow label="Audience">
            {sources} — opted-out contacts are always excluded
          </ReviewRow>
          <ReviewRow label="Launches">
            {formData.start_immediately || !formData.scheduled_start ? (
              <Badge variant="secondary">Immediately</Badge>
            ) : (
              formatLongDate(new Date(formData.scheduled_start))
            )}
          </ReviewRow>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            What a {formatCurrency(formData.example_job_amount)} job looks like
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <ReviewRow label="Customer pays today">
            {formatCurrency(example.depositDueToday)}
          </ReviewRow>
          <ReviewRow label="Balance at service">
            {formatCurrency(example.balanceAtService)}
          </ReviewRow>
          <ReviewRow label="They save">
            {formatCurrency(example.savings)}
          </ReviewRow>
        </CardContent>
      </Card>
    </div>
  );
}

function ReviewRow({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-4">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right font-medium">{children}</span>
    </div>
  );
}
