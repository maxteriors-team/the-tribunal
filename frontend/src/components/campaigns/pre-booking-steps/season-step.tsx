"use client";

import { CalendarRange } from "lucide-react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  MONTH_OPTIONS,
  nextSeasonYear,
  resolveSeasonWindow,
} from "@/lib/pre-booking";
import { formatLongDate } from "@/lib/utils/date";

import type { WizardErrors, WizardStep } from "../wizard-types";

export interface SeasonStepFields {
  service_season_start_month: number;
  service_season_end_month: number;
  service_season_year: number;
  service_description: string;
}

export function validateSeason(data: SeasonStepFields): WizardErrors {
  const errors: WizardErrors = {};
  if (!data.service_description.trim()) {
    errors.service_description = "Describe the work you're pre-selling";
  } else if (data.service_description.trim().length > 200) {
    errors.service_description = "Keep the description under 200 characters";
  }
  if (!Number.isInteger(data.service_season_year) || data.service_season_year < 2000) {
    errors.service_season_year = "Enter the year the season starts in";
  }
  return errors;
}

/**
 * "Season" step: which months the work actually happens in.
 *
 * The operator picks months, not dates, because that is how a season is
 * thought about ("March through May"). A season is allowed to wrap the new
 * year — November through February is one holiday-lighting season, not two —
 * so the year asked for is the year the season *starts* in and the end year is
 * derived.
 */
export function makeSeasonStep<
  TStepId extends string,
  TFormData extends SeasonStepFields,
>(opts: { id: TStepId }): WizardStep<TStepId, TFormData> {
  return {
    id: opts.id,
    label: "Season",
    icon: CalendarRange,
    validate: (data) => validateSeason(data),
    render: ({ formData, errors, updateField }) => {
      const setField = <K extends keyof SeasonStepFields>(
        key: K,
        value: SeasonStepFields[K],
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

      const handleStartMonthChange = (value: string) => {
        const startMonth = Number(value);
        setField("service_season_start_month", startMonth);
        // Guard rail: silently pointing a campaign at a season that has already
        // begun is the single easiest way to waste a month of sends, so roll the
        // year forward when the new start month is already behind us.
        const start = new Date(formData.service_season_year, startMonth - 1, 1);
        if (start.getTime() <= Date.now()) {
          setField("service_season_year", nextSeasonYear({ startMonth }));
        }
      };

      return (
        <div className="space-y-6">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <div className="space-y-2">
              <Label htmlFor="season-start-month">Season Starts *</Label>
              <Select
                value={String(formData.service_season_start_month)}
                onValueChange={handleStartMonthChange}
              >
                <SelectTrigger id="season-start-month">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {MONTH_OPTIONS.map((month) => (
                    <SelectItem key={month.value} value={String(month.value)}>
                      {month.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="season-end-month">Season Ends *</Label>
              <Select
                value={String(formData.service_season_end_month)}
                onValueChange={(v) =>
                  setField("service_season_end_month", Number(v))
                }
              >
                <SelectTrigger id="season-end-month">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {MONTH_OPTIONS.map((month) => (
                    <SelectItem key={month.value} value={String(month.value)}>
                      {month.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="season-year">Starting Year *</Label>
              <Input
                id="season-year"
                type="number"
                min={new Date().getFullYear()}
                value={formData.service_season_year}
                onChange={(e) =>
                  setField("service_season_year", Number(e.target.value))
                }
                className={errors.service_season_year ? "border-destructive" : ""}
              />
              {errors.service_season_year && (
                <p className="text-sm text-destructive">
                  {errors.service_season_year}
                </p>
              )}
            </div>
          </div>

          <div className="rounded-lg border bg-muted/50 p-4">
            <p className="font-medium">{season.label}</p>
            <p className="mt-1 text-sm text-muted-foreground">
              The work happens between {formatLongDate(season.start)} and{" "}
              {formatLongDate(season.end)}.
            </p>
            {season.start.getFullYear() !== season.end.getFullYear() && (
              <p className="mt-1 text-sm text-muted-foreground">
                This season wraps the new year — it is treated as one season, not
                two.
              </p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="service-description">What You&apos;re Selling *</Label>
            <Input
              id="service-description"
              placeholder="e.g., Spring house wash + gutter clean-out"
              maxLength={200}
              value={formData.service_description}
              onChange={(e) => setField("service_description", e.target.value)}
              className={errors.service_description ? "border-destructive" : ""}
            />
            {errors.service_description ? (
              <p className="text-sm text-destructive">
                {errors.service_description}
              </p>
            ) : (
              <p className="text-xs text-muted-foreground">
                Appears on the quote the customer pays their deposit through.
              </p>
            )}
          </div>
        </div>
      );
    },
  };
}
