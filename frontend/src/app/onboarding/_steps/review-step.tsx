"use client";

import { useFormContext } from "react-hook-form";
import { AlertCircle, CheckCircle2, Phone, Users } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import { formatNumber } from "@/lib/utils/number";

import type { OnboardingFormValues } from "../_state";
import { useOnboardingExtras } from "./onboarding-context";

export function ReviewStep() {
  const form = useFormContext<OnboardingFormValues>();
  const {
    fubConnected,
    fubName,
    fubImportCount,
    calcomConnected,
    calcomUsername,
    csvFile,
    csvRowCount,
  } = useOnboardingExtras();

  const bookingUrl = form.watch("calcom_booking_url");
  const areaCode = form.watch("area_code");

  const totalLeads = (fubImportCount ?? 0) + (csvRowCount ?? 0);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold">Ready to Launch</h2>
        <p className="text-muted-foreground mt-1">
          Review your setup and launch your lead reactivation campaign.
        </p>
      </div>

      <Card>
        <CardContent className="pt-4 pb-4 divide-y divide-border">
          <div className="flex items-center gap-3 py-3">
            {fubConnected ? (
              <CheckCircle2 className="size-5 text-green-500 shrink-0" />
            ) : (
              <AlertCircle className="size-5 text-amber-500 shrink-0" />
            )}
            <div className="min-w-0">
              <p className="text-sm font-medium">
                {fubConnected
                  ? "Follow Up Boss connected"
                  : "Follow Up Boss not connected"}
              </p>
              {fubName && (
                <p className="text-xs text-muted-foreground">{fubName}</p>
              )}
            </div>
          </div>

          <div className="flex items-center gap-3 py-3">
            {calcomConnected ? (
              <CheckCircle2 className="size-5 text-green-500 shrink-0" />
            ) : (
              <AlertCircle className="size-5 text-amber-500 shrink-0" />
            )}
            <div className="min-w-0">
              <p className="text-sm font-medium">
                {calcomConnected
                  ? "Cal.com connected"
                  : "Cal.com not connected"}
              </p>
              {calcomUsername && (
                <p className="text-xs text-muted-foreground truncate">
                  @{calcomUsername}
                </p>
              )}
              {bookingUrl && (
                <p className="text-xs text-muted-foreground truncate">
                  {bookingUrl}
                </p>
              )}
            </div>
          </div>

          <div className="flex items-center gap-3 py-3">
            <Users className="size-5 text-muted-foreground shrink-0" />
            <div className="min-w-0">
              <p className="text-sm font-medium">
                {totalLeads > 0
                  ? `${formatNumber(totalLeads)} lead${totalLeads !== 1 ? "s" : ""} to contact`
                  : "No leads imported yet"}
              </p>
              <div className="text-xs text-muted-foreground space-y-0.5">
                {fubImportCount !== null && fubImportCount > 0 && (
                  <p>{formatNumber(fubImportCount)} from Follow Up Boss</p>
                )}
                {csvFile && csvRowCount !== null && (
                  <p>
                    ~{formatNumber(csvRowCount)} from {csvFile.name}
                  </p>
                )}
              </div>
            </div>
          </div>

          <div className="flex items-center gap-3 py-3">
            <Phone className="size-5 text-muted-foreground shrink-0" />
            <div>
              <p className="text-sm font-medium">
                {areaCode ? `Area code ${areaCode}` : "Any US number"}
              </p>
              <p className="text-xs text-muted-foreground">
                Texting number preference
              </p>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
