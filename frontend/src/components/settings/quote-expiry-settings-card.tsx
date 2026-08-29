"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { useSettingsSaveMutation } from "@/hooks/useSettingsSaveMutation";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { salesWizardApi } from "@/lib/api/sales-wizard";
import { queryKeys } from "@/lib/query-keys";

const DEFAULT_VALIDITY_DAYS = 30;
const MIN_VALIDITY_DAYS = 1;
const MAX_VALIDITY_DAYS = 365;

/**
 * Controls whether quotes lapse, and how long they hold.
 *
 * Lives beside quote revival because both answer the same operator question —
 * what happens to a quote nobody accepted. The window is stamped on *send*, so
 * changing it never moves a deadline a customer has already been shown.
 */
export function QuoteExpirySettingsCard() {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();

  const { data: pricing, isPending } = useQuery({
    queryKey: queryKeys.salesWizard.pricing(workspaceId ?? ""),
    queryFn: () => salesWizardApi.getPricing(workspaceId!),
    enabled: Boolean(workspaceId),
  });

  const [expiryEnabled, setExpiryEnabled] = useState(true);
  const [validityDays, setValidityDays] = useState(String(DEFAULT_VALIDITY_DAYS));
  // Snapshot of the server config the draft was seeded from, so a save that
  // replaces the cached copy re-seeds the fields instead of stranding them.
  const [serverPricing, setServerPricing] = useState<typeof pricing>(undefined);

  // Adjusting state during render behind an identity guard is the sanctioned
  // React pattern here (see seasonal-pricing-settings-tab) and avoids the
  // cascading extra render an effect would cost.
  if (pricing && pricing !== serverPricing) {
    setServerPricing(pricing);
    setExpiryEnabled(pricing.quote_expiry_enabled ?? true);
    setValidityDays(String(pricing.quote_validity_days ?? DEFAULT_VALIDITY_DAYS));
  }

  const mutation = useSettingsSaveMutation({
    mutationFn: (update: { quote_expiry_enabled: boolean; quote_validity_days: number }) =>
      salesWizardApi.updatePricing(workspaceId!, update),
    successMessage: "Quote expiry settings saved.",
    errorMessage: "We couldn't save quote expiry settings. Check your connection and try again.",
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.salesWizard.pricing(workspaceId ?? ""), updated);
    },
  });

  const parsedDays = Number(validityDays);
  const daysInvalid =
    expiryEnabled &&
    (!Number.isInteger(parsedDays) ||
      parsedDays < MIN_VALIDITY_DAYS ||
      parsedDays > MAX_VALIDITY_DAYS);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Quote expiry</CardTitle>
        <CardDescription>
          A sent quote stops being acceptable after its window, so a stale price can&apos;t be taken
          up months later. Turn it off if your prices hold indefinitely.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="flex items-start justify-between gap-4">
          <div className="space-y-1">
            <Label htmlFor="quote-expiry-enabled">Quotes expire</Label>
            <p className="text-sm text-muted-foreground">
              {expiryEnabled
                ? "New sends get a deadline. Quotes already sent keep the date the customer was shown."
                : "New sends carry no deadline and never lapse."}
            </p>
          </div>
          <Switch
            id="quote-expiry-enabled"
            checked={expiryEnabled}
            onCheckedChange={setExpiryEnabled}
            disabled={isPending || mutation.isPending}
          />
        </div>

        {expiryEnabled && (
          <div className="space-y-1.5">
            <Label htmlFor="quote-validity-days">Days a quoted price holds</Label>
            <Input
              id="quote-validity-days"
              type="number"
              inputMode="numeric"
              min={MIN_VALIDITY_DAYS}
              max={MAX_VALIDITY_DAYS}
              value={validityDays}
              onChange={(event) => setValidityDays(event.target.value)}
              disabled={isPending || mutation.isPending}
              className="max-w-32"
              aria-invalid={daysInvalid}
            />
            <p className="text-sm text-muted-foreground">
              {daysInvalid
                ? `Enter a whole number between ${MIN_VALIDITY_DAYS} and ${MAX_VALIDITY_DAYS}.`
                : "Counted from the day the quote is sent, not the day it was drafted."}
            </p>
          </div>
        )}

        <Button
          onClick={() =>
            mutation.mutate({
              quote_expiry_enabled: expiryEnabled,
              // The server ignores this while expiry is off, but sending the
              // last good value keeps the number intact for when it is switched
              // back on rather than resetting it to the default.
              quote_validity_days: daysInvalid ? DEFAULT_VALIDITY_DAYS : parsedDays,
            })
          }
          disabled={isPending || mutation.isPending || daysInvalid}
        >
          {mutation.isPending ? "Saving…" : "Save"}
        </Button>
      </CardContent>
    </Card>
  );
}
