"use client";

import { AlertCircle, AlertTriangle, CheckCircle2, Phone, Users } from "lucide-react";
import Link from "next/link";
import { useFormContext } from "react-hook-form";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Card, CardContent } from "@/components/ui/card";
import { formatNumber } from "@/lib/utils/number";

import type { OnboardingFormValues } from "../_state";

import { useOnboardingExtras } from "./onboarding-context";

export interface ReviewStepProps {
  /** Set after launch when Telnyx auto-purchase produced no SMS number. */
  showPhoneWarning?: boolean;
}

export function ReviewStep({ showPhoneWarning = false }: ReviewStepProps) {
  const form = useFormContext<OnboardingFormValues>();
  const { calcomConnected, calcomUsername, csvFile, csvRowCount } =
    useOnboardingExtras();

  const bookingUrl = form.watch("calcom_booking_url");
  const areaCode = form.watch("area_code");

  const totalLeads = csvRowCount ?? 0;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold">Ready to Launch</h2>
        <p className="text-muted-foreground mt-1">
          Review your setup and launch your lead reactivation campaign.
        </p>
      </div>

      {showPhoneWarning && (
        <Alert className="border-amber-500/50 text-amber-700 dark:text-amber-400 [&>svg]:text-amber-500">
          <AlertTriangle className="size-4" />
          <AlertTitle>No SMS number yet</AlertTitle>
          <AlertDescription className="text-muted-foreground">
            We couldn&apos;t get you an SMS number automatically — add one to
            start texting. A phone number is required to launch SMS and voice
            campaigns.{" "}
            <Link
              href="/settings?tab=integrations"
              target="_blank"
              rel="noopener noreferrer"
              className="font-medium text-foreground underline underline-offset-4"
            >
              Add a phone number
            </Link>
            , then launch again.
          </AlertDescription>
        </Alert>
      )}

      <Card>
        <CardContent className="pt-4 pb-4 divide-y divide-border">
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
