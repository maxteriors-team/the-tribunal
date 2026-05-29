"use client";

import { Clock, Eye, FileText, Users } from "lucide-react";
import type { Dispatch, ReactNode, SetStateAction } from "react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { PhoneNumber } from "@/types";

import {
  BasicsStep,
  ContactsStep,
  ReviewScheduleCard,
  ReviewSummaryCard,
  ScheduleStep,
} from "../steps";
import type { WizardStep } from "../wizard-types";

import {
  type BasicsFields,
  type ScheduleFields,
} from "./form-types";
import {
  validateBasics,
  validateContacts,
  validateSchedule,
} from "./validators";

/**
 * Build the "Basics" step (name + description + from-phone). Both wizards
 * use the same fields, only the placeholder copy differs.
 */
export function makeBasicsStep<
  TStepId extends string,
  TFormData extends BasicsFields,
>(opts: {
  id: TStepId;
  phoneNumbers: PhoneNumber[];
  namePlaceholder: string;
  emptyPhoneLabel: string;
}): WizardStep<TStepId, TFormData> {
  return {
    id: opts.id,
    label: "Basics",
    icon: FileText,
    validate: (data) => validateBasics(data),
    render: ({ formData, errors, updateField }) => (
      <BasicsStep
        name={formData.name}
        description={formData.description}
        fromPhoneNumber={formData.from_phone_number}
        phoneNumbers={opts.phoneNumbers}
        errors={errors}
        onNameChange={(v) =>
          updateField("name" as keyof TFormData, v as TFormData[keyof TFormData])
        }
        onDescriptionChange={(v) =>
          updateField(
            "description" as keyof TFormData,
            v as TFormData[keyof TFormData],
          )
        }
        onPhoneChange={(v) =>
          updateField(
            "from_phone_number" as keyof TFormData,
            v as TFormData[keyof TFormData],
          )
        }
        namePlaceholder={opts.namePlaceholder}
        emptyPhoneLabel={opts.emptyPhoneLabel}
      />
    ),
  };
}

/**
 * Build the "Contacts" step. Selected ids live in the parent wizard state
 * so the setter is passed in.
 */
export function makeContactsStep<
  TStepId extends string,
  TFormData extends object,
>(opts: {
  id: TStepId;
  workspaceId: string;
  selectedContactIds: Set<number>;
  setSelectedContactIds: Dispatch<SetStateAction<Set<number>>>;
}): WizardStep<TStepId, TFormData> {
  return {
    id: opts.id,
    label: "Contacts",
    icon: Users,
    validate: () => validateContacts(opts.selectedContactIds.size),
    render: ({ errors }) => (
      <ContactsStep
        workspaceId={opts.workspaceId}
        selectedIds={opts.selectedContactIds}
        onSelectionChange={opts.setSelectedContactIds}
        error={errors.contacts}
      />
    ),
  };
}

/**
 * Build the "Schedule" step. The rate-limiting controls are channel
 * specific so they are passed in as a slot via `renderRateLimiting`.
 */
export function makeScheduleStep<
  TStepId extends string,
  TFormData extends ScheduleFields,
>(opts: {
  id: TStepId;
  sendingHoursLabel: string;
  sendingHoursDescription: string;
  daysLabel: string;
  renderRateLimiting?: (args: {
    formData: TFormData;
    updateField: <K extends keyof TFormData>(
      key: K,
      value: TFormData[K],
    ) => void;
  }) => ReactNode;
}): WizardStep<TStepId, TFormData> {
  return {
    id: opts.id,
    label: "Schedule",
    icon: Clock,
    validate: (data) => validateSchedule(data),
    render: ({ formData, errors, updateField }) => (
      <ScheduleStep
        scheduledStart={formData.scheduled_start}
        scheduledEnd={formData.scheduled_end}
        sendingHoursEnabled={formData.sending_hours_enabled}
        sendingHoursStart={formData.sending_hours_start}
        sendingHoursEnd={formData.sending_hours_end}
        sendingDays={formData.sending_days}
        timezone={formData.timezone}
        errors={errors}
        onScheduledStartChange={(v) =>
          updateField(
            "scheduled_start" as keyof TFormData,
            v as TFormData[keyof TFormData],
          )
        }
        onScheduledEndChange={(v) =>
          updateField(
            "scheduled_end" as keyof TFormData,
            v as TFormData[keyof TFormData],
          )
        }
        onSendingHoursEnabledChange={(v) =>
          updateField(
            "sending_hours_enabled" as keyof TFormData,
            v as TFormData[keyof TFormData],
          )
        }
        onSendingHoursStartChange={(v) =>
          updateField(
            "sending_hours_start" as keyof TFormData,
            v as TFormData[keyof TFormData],
          )
        }
        onSendingHoursEndChange={(v) =>
          updateField(
            "sending_hours_end" as keyof TFormData,
            v as TFormData[keyof TFormData],
          )
        }
        onSendingDaysChange={(v) =>
          updateField(
            "sending_days" as keyof TFormData,
            v as TFormData[keyof TFormData],
          )
        }
        onTimezoneChange={(v) =>
          updateField(
            "timezone" as keyof TFormData,
            v as TFormData[keyof TFormData],
          )
        }
        sendingHoursLabel={opts.sendingHoursLabel}
        sendingHoursDescription={opts.sendingHoursDescription}
        daysLabel={opts.daysLabel}
        rateLimitingSlot={
          opts.renderRateLimiting?.({ formData, updateField })
        }
      />
    ),
  };
}

/**
 * Build the "Review" step. The summary + recipients + schedule cards are
 * always rendered; channel-specific cards slot in via `renderChannelCards`.
 */
export function makeReviewStep<
  TStepId extends string,
  TFormData extends BasicsFields & ScheduleFields,
>(opts: {
  id: TStepId;
  phoneNumbers: PhoneNumber[];
  selectedContactIds: Set<number>;
  recipientsLabel: string;
  scheduleHoursLabel: string;
  renderRateDescription: (formData: TFormData) => ReactNode;
  renderChannelCards: (formData: TFormData) => ReactNode;
}): WizardStep<TStepId, TFormData> {
  return {
    id: opts.id,
    label: "Review",
    icon: Eye,
    render: ({ formData }) => {
      const selectedPhone = opts.phoneNumbers.find(
        (p) => p.phone_number === formData.from_phone_number,
      );
      return (
        <div className="space-y-6">
          <ReviewSummaryCard
            name={formData.name}
            description={formData.description || undefined}
            fromPhoneDisplay={getSenderDisplayName(selectedPhone, formData.from_phone_number)}
          />

          <Card>
            <CardHeader>
              <CardTitle className="text-lg flex items-center gap-2">
                <Users className="size-5" />
                Recipients
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex items-center gap-2">
                <Badge variant="secondary" className="text-lg px-3 py-1">
                  {opts.selectedContactIds.size}
                </Badge>
                <span className="text-muted-foreground">
                  {opts.recipientsLabel}
                </span>
              </div>
            </CardContent>
          </Card>

          {opts.renderChannelCards(formData)}

          <ReviewScheduleCard
            sendingHoursEnabled={formData.sending_hours_enabled}
            sendingHoursStart={formData.sending_hours_start}
            sendingHoursEnd={formData.sending_hours_end}
            sendingDays={formData.sending_days}
            timezone={formData.timezone}
            hoursLabel={opts.scheduleHoursLabel}
            rateDescription={opts.renderRateDescription(formData)}
          />
        </div>
      );
    },
  };
}

function getSenderDisplayName(
  phoneNumber: PhoneNumber | undefined,
  fallbackPhoneNumber: string,
): string {
  if (!phoneNumber) return fallbackPhoneNumber;

  const senderAddress = phoneNumber.mac_relay_sender_id || phoneNumber.phone_number;
  const label = phoneNumber.friendly_name || senderAddress;
  return phoneNumber.imessage_enabled ? `${label} · iMessage` : label;
}
