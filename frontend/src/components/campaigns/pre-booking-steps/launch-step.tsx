"use client";

import { CalendarClock, CheckCircle2, TriangleAlert } from "lucide-react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  AMPLE_LEAD_DAYS,
  assessLeadTime,
  leadTimeDays,
  resolveSeasonWindow,
  type LeadTime,
} from "@/lib/pre-booking";
import { formatLongDate } from "@/lib/utils/date";

import type { WizardErrors, WizardStep } from "../wizard-types";

import type { SeasonStepFields } from "./season-step";

export interface LaunchStepFields {
  /**
   * `datetime-local` string. Doubles as the campaign's `scheduled_start`, so
   * there is exactly one launch date on the record.
   */
  scheduled_start?: string;
  start_immediately: boolean;
}

export function validateLaunch(
  data: LaunchStepFields & SeasonStepFields,
): WizardErrors {
  if (data.start_immediately) return {};
  if (!data.scheduled_start) {
    return { scheduled_start: "Pick a launch date, or start immediately" };
  }
  if (new Date(data.scheduled_start).getTime() <= Date.now()) {
    return { scheduled_start: "The launch date must be in the future" };
  }
  return {};
}

/** The launch instant a form is currently describing. */
export function resolveLaunchDate(data: LaunchStepFields): Date {
  if (!data.start_immediately && data.scheduled_start) {
    return new Date(data.scheduled_start);
  }
  return new Date();
}

/** Lead time for the season + launch date a form currently describes. */
export function resolveLeadTime(
  data: LaunchStepFields & SeasonStepFields,
): LeadTime {
  const { start } = resolveSeasonWindow({
    startMonth: data.service_season_start_month,
    endMonth: data.service_season_end_month,
    year: data.service_season_year,
  });
  return assessLeadTime(
    leadTimeDays({ launchOn: resolveLaunchDate(data), seasonStart: start }),
  );
}

const LEAD_TIME_STYLES = {
  ample: {
    container: "border-success/50 bg-success/10 text-success",
    heading: "Plenty of runway",
    Icon: CheckCircle2,
  },
  tight: {
    container: "border-amber-500/50 bg-amber-500/10 text-amber-600",
    heading: "Tight, but workable",
    Icon: TriangleAlert,
  },
  late: {
    container: "border-destructive/50 bg-destructive/10 text-destructive",
    heading: "Too late to pre-book this season",
    Icon: TriangleAlert,
  },
} as const;

/**
 * The lead-time verdict, stated loudly.
 *
 * This is the whole point of the feature: the right time to build a
 * January–March campaign is September. A campaign launched three weeks before
 * the season is a discount with no planning value, and the operator needs to
 * see that before spending a month of sends on it — not after.
 */
export function LeadTimeCallout({
  leadTime,
  seasonLabel,
  seasonStart,
}: {
  leadTime: LeadTime;
  seasonLabel: string;
  seasonStart: Date;
}) {
  const { container, heading, Icon } = LEAD_TIME_STYLES[leadTime.status];
  const idealLaunch = new Date(seasonStart);
  idealLaunch.setDate(idealLaunch.getDate() - AMPLE_LEAD_DAYS);

  return (
    <div className={`rounded-lg border p-4 ${container}`}>
      <div className="flex items-start gap-3">
        <Icon className="mt-0.5 size-5 shrink-0" />
        <div className="space-y-1">
          <p className="font-semibold">
            {heading} — {leadTime.days} day{leadTime.days === 1 ? "" : "s"} until{" "}
            {seasonLabel} opens
          </p>
          <p className="text-sm">{leadTime.message}</p>
          <p className="text-sm opacity-90">
            The rule: build January–March in September. Launching on or before{" "}
            {formatLongDate(idealLaunch)} keeps {AMPLE_LEAD_DAYS}+ days of runway
            for this season.
          </p>
        </div>
      </div>
    </div>
  );
}

/**
 * "Launch" step: when the campaign goes out, graded against the season.
 *
 * Scheduling months ahead is the normal path here, not the exception — the
 * campaign sits in `scheduled` until the worker picks it up on the date chosen.
 */
export function makeLaunchStep<
  TStepId extends string,
  TFormData extends LaunchStepFields & SeasonStepFields,
>(opts: { id: TStepId }): WizardStep<TStepId, TFormData> {
  return {
    id: opts.id,
    label: "Launch",
    icon: CalendarClock,
    validate: (data) => validateLaunch(data),
    render: ({ formData, errors, updateField }) => {
      const setField = <K extends keyof LaunchStepFields>(
        key: K,
        value: LaunchStepFields[K],
      ) =>
        updateField(
          key as unknown as keyof TFormData,
          value as unknown as TFormData[keyof TFormData],
        );

      const season = resolveSeasonWindow({
        startMonth: formData.service_season_start_month,
        endMonth: formData.service_season_end_month,
        year: formData.service_season_year,
      });

      return (
        <div className="space-y-6">
          <LeadTimeCallout
            leadTime={resolveLeadTime(formData)}
            seasonLabel={season.label}
            seasonStart={season.start}
          />

          <div className="space-y-2">
            <Label htmlFor="launch-at">Launch On *</Label>
            <Input
              id="launch-at"
              type="datetime-local"
              value={formData.scheduled_start ?? ""}
              disabled={formData.start_immediately}
              onChange={(e) =>
                setField("scheduled_start", e.target.value || undefined)
              }
              className={errors.scheduled_start ? "border-destructive" : ""}
            />
            {errors.scheduled_start ? (
              <p className="text-sm text-destructive">
                {errors.scheduled_start}
              </p>
            ) : (
              <p className="text-xs text-muted-foreground">
                The campaign waits in &quot;scheduled&quot; until this moment,
                then sends itself.
              </p>
            )}
          </div>

          <div className="flex items-center justify-between rounded-lg bg-muted/50 p-4">
            <div className="pr-4">
              <Label htmlFor="start-immediately" className="font-medium">
                Start immediately instead
              </Label>
              <p className="text-sm text-muted-foreground">
                Send as soon as the campaign is created. Only sensible when the
                season is already close.
              </p>
            </div>
            <Switch
              id="start-immediately"
              checked={formData.start_immediately}
              onCheckedChange={(v) => setField("start_immediately", v)}
            />
          </div>
        </div>
      );
    },
  };
}
