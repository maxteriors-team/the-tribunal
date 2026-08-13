"use client";

import { CheckCircle2 } from "lucide-react";

import { GoogleCalendarCard } from "@/components/settings/google-calendar-card";

export function GoogleCalendarStep() {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold">Connect Your Calendar</h2>
        <p className="mt-1 text-muted-foreground">
          The AI checks your real availability before offering a time and creates confirmed meetings
          on your own Google Calendar.
        </p>
      </div>

      <GoogleCalendarCard returnPath="/onboarding" />

      <div className="flex items-start gap-3 rounded-lg border bg-muted/30 p-4 text-sm">
        <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-green-600" aria-hidden="true" />
        <p>
          You can continue without connecting and finish this later in Settings. Availability will
          not be offered until a bookable rep has connected their calendar.
        </p>
      </div>
    </div>
  );
}
