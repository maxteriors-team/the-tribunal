"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertCircle, ShieldOff, Users } from "lucide-react";
import { useMemo } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { useDebounce } from "@/hooks/useDebounce";
import { preBookingApi } from "@/lib/api/pre-booking-campaigns";
import { queryKeys } from "@/lib/query-keys";
import { formatNumber } from "@/lib/utils/number";

import type { WizardErrors, WizardStep } from "../wizard-types";

export interface AudienceStepFields {
  include_past_customers: boolean;
  include_unsold_quotes: boolean;
  /** Last season's holiday-lighting customers. Opt-in; see the step copy. */
  include_prior_season_christmas: boolean;
}

export function validateAudience(data: AudienceStepFields): WizardErrors {
  // The seasonal slice counts on its own: a renewal push is built by turning the
  // two broad slices off and leaving only this one on.
  return data.include_past_customers ||
    data.include_unsold_quotes ||
    data.include_prior_season_christmas
    ? {}
    : { audience: "Pick at least one source of warm contacts" };
}

interface AudienceStepProps extends AudienceStepFields {
  workspaceId: string;
  error?: string;
  onToggle: (key: keyof AudienceStepFields, value: boolean) => void;
}

/**
 * Live audience sizing, workspace-level, before the campaign row exists.
 *
 * The count is the number that decides whether the campaign is worth building
 * at all, so it is fetched as the operator flips sources rather than after the
 * fact. Debounced because each toggle is a database-wide count.
 */
function AudienceStep({
  workspaceId,
  include_past_customers,
  include_unsold_quotes,
  include_prior_season_christmas,
  error,
  onToggle,
}: AudienceStepProps) {
  // Memoised before debouncing: a fresh object every render would keep resetting
  // the debounce timer and never settle.
  const requested = useMemo(
    () => ({
      include_past_customers,
      include_unsold_quotes,
      include_prior_season_christmas,
    }),
    [
      include_past_customers,
      include_unsold_quotes,
      include_prior_season_christmas,
    ],
  );
  const params = useDebounce(requested, 300);

  const {
    data: audience,
    isFetching,
    error: previewError,
  } = useQuery({
    queryKey: queryKeys.preBooking.audience(workspaceId, params),
    queryFn: () => preBookingApi.previewWorkspaceAudience(workspaceId, params),
    enabled:
      !!workspaceId &&
      (params.include_past_customers ||
        params.include_unsold_quotes ||
        params.include_prior_season_christmas),
  });

  const total = audience?.total ?? 0;

  return (
    <div className="space-y-6">
      {error && (
        <Alert variant="destructive">
          <AlertCircle className="size-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <div className="space-y-4">
        <div>
          <h4 className="font-medium">Who Hears About It</h4>
          <p className="text-sm text-muted-foreground">
            Pre-booking sells to people who already know you. There is no cold
            list here — a deposit months ahead of the work is a trust purchase.
          </p>
        </div>

        <div className="flex items-center justify-between rounded-lg bg-muted/50 p-4">
          <div className="pr-4">
            <Label htmlFor="include-past-customers" className="font-medium">
              Past customers
            </Label>
            <p className="text-sm text-muted-foreground">
              People you have already done work for.
              {audience && ` ${formatNumber(audience.past_customers)} available.`}
            </p>
          </div>
          <Switch
            id="include-past-customers"
            checked={include_past_customers}
            onCheckedChange={(v) => onToggle("include_past_customers", v)}
          />
        </div>

        <div className="flex items-center justify-between rounded-lg bg-muted/50 p-4">
          <div className="pr-4">
            <Label htmlFor="include-unsold-quotes" className="font-medium">
              Unsold quotes
            </Label>
            <p className="text-sm text-muted-foreground">
              Estimates that never closed — the price is often the only thing
              that was wrong.
              {audience && ` ${formatNumber(audience.unsold_quotes)} available.`}
            </p>
          </div>
          <Switch
            id="include-unsold-quotes"
            checked={include_unsold_quotes}
            onCheckedChange={(v) => onToggle("include_unsold_quotes", v)}
          />
        </div>

        {/* The count is printed whether or not the slice is selected — the
            server counts every slice regardless — so the operator can see how
            many homes were lit last season *before* deciding to aim at them. */}
        <div className="flex items-center justify-between rounded-lg bg-muted/50 p-4">
          <div className="pr-4">
            <Label
              htmlFor="include-prior-season-christmas"
              className="font-medium"
            >
              Last season&apos;s holiday-lighting customers
            </Label>
            <p className="text-sm text-muted-foreground">
              The homes you lit last Christmas — the cheapest bookings of the
              winter, because the crew knows the roof and the measurements are
              already on file. Much narrower than the two above, which take
              anyone you have ever worked for or quoted: this is one service,
              one season. A renewal push means turning those two off and
              leaving only this one on.
              {audience &&
                ` ${formatNumber(audience.prior_season_christmas)} lit last season.`}
            </p>
          </div>
          <Switch
            id="include-prior-season-christmas"
            checked={include_prior_season_christmas}
            onCheckedChange={(v) =>
              onToggle("include_prior_season_christmas", v)
            }
          />
        </div>
      </div>

      <div className="rounded-lg border p-4">
        <div className="flex items-center gap-3">
          <Users className="size-5 text-muted-foreground" />
          {isFetching && !audience ? (
            <Skeleton className="h-8 w-24" />
          ) : (
            <Badge variant="secondary" className="px-3 py-1 text-lg">
              {formatNumber(total)}
            </Badge>
          )}
          <span className="text-muted-foreground">
            warm contacts will be enrolled
          </span>
        </div>

        {previewError && (
          <p className="mt-3 text-sm text-destructive">
            Could not size the audience right now. The campaign can still be
            built; enrolment happens when it is created.
          </p>
        )}

        {audience && (
          <div className="mt-4 space-y-2 text-sm">
            {/* Suppression is stated out loud rather than folded into the total:
                the operator should see that the list is smaller because people
                opted out, not wonder where the contacts went. */}
            <div className="flex items-start gap-2 text-muted-foreground">
              <ShieldOff className="mt-0.5 size-4 shrink-0" />
              <span>
                {formatNumber(audience.excluded_opted_out)} warm contact
                {audience.excluded_opted_out === 1 ? " is" : "s are"} held back
                because they opted out.
              </span>
            </div>
            {audience.excluded_already_enrolled > 0 && (
              <p className="text-muted-foreground">
                {formatNumber(audience.excluded_already_enrolled)} already
                enrolled in this campaign and will not be messaged twice.
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * "Audience" step. Replaces the usual contact-selector step: a pre-booking
 * audience is defined by *rules* (past customers, unsold quotes, last season's
 * lighting customers) evaluated server-side at enrol time, not by hand-picking
 * rows out of a list.
 */
export function makeAudienceStep<
  TStepId extends string,
  TFormData extends AudienceStepFields,
>(opts: { id: TStepId; workspaceId: string }): WizardStep<TStepId, TFormData> {
  return {
    id: opts.id,
    label: "Audience",
    icon: Users,
    validate: (data) => validateAudience(data),
    render: ({ formData, errors, updateField }) => (
      <AudienceStep
        workspaceId={opts.workspaceId}
        include_past_customers={formData.include_past_customers}
        include_unsold_quotes={formData.include_unsold_quotes}
        include_prior_season_christmas={formData.include_prior_season_christmas}
        error={errors.audience}
        onToggle={(key, value) =>
          updateField(
            key as unknown as keyof TFormData,
            value as unknown as TFormData[keyof TFormData],
          )
        }
      />
    ),
  };
}
