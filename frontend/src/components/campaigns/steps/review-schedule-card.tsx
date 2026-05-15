import type React from "react";
import { Clock } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

import { DAYS_OF_WEEK } from "@/lib/constants";

interface ReviewScheduleCardProps {
  sendingHoursEnabled: boolean;
  sendingHoursStart: string;
  sendingHoursEnd: string;
  sendingDays: number[];
  timezone: string;
  hoursLabel?: string;
  rateDescription: React.ReactNode;
}

export function ReviewScheduleCard({
  sendingHoursEnabled,
  sendingHoursStart,
  sendingHoursEnd,
  sendingDays,
  timezone,
  hoursLabel = "Sending hours",
  rateDescription,
}: ReviewScheduleCardProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg flex items-center gap-2">
          <Clock className="size-5" />
          Schedule
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        <div className="flex items-center gap-2 text-sm">
          <span className="text-muted-foreground">{hoursLabel}:</span>
          <span>
            {sendingHoursEnabled
              ? `${sendingHoursStart} - ${sendingHoursEnd} (${timezone.replace("America/", "")})`
              : "Anytime (no restrictions)"}
          </span>
        </div>
        <div className="flex items-center gap-2 text-sm">
          <span className="text-muted-foreground">Days:</span>
          <span>
            {sendingDays
              .map((d) => DAYS_OF_WEEK.find((day) => day.value === d)?.label)
              .join(", ")}
          </span>
        </div>
        <div className="flex items-center gap-2 text-sm">
          <span className="text-muted-foreground">Rate:</span>
          <span>{rateDescription}</span>
        </div>
      </CardContent>
    </Card>
  );
}
