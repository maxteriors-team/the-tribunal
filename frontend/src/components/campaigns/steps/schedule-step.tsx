"use client";

import { Clock, Calendar } from "lucide-react";
import { motion } from "motion/react";
import type React from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import { DAYS_OF_WEEK, TIMEZONES } from "@/lib/constants";

interface ScheduleStepProps {
  scheduledStart?: string;
  scheduledEnd?: string;
  sendingHoursEnabled: boolean;
  sendingHoursStart: string;
  sendingHoursEnd: string;
  sendingDays: number[];
  timezone: string;
  errors: Record<string, string>;
  onScheduledStartChange: (value: string | undefined) => void;
  onScheduledEndChange: (value: string | undefined) => void;
  onSendingHoursEnabledChange: (value: boolean) => void;
  onSendingHoursStartChange: (value: string) => void;
  onSendingHoursEndChange: (value: string) => void;
  onSendingDaysChange: (value: number[]) => void;
  onTimezoneChange: (value: string) => void;
  sendingHoursLabel?: string;
  sendingHoursDescription?: string;
  daysLabel?: string;
  rateLimitingSlot?: React.ReactNode;
}

export function ScheduleStep({
  scheduledStart,
  scheduledEnd,
  sendingHoursEnabled,
  sendingHoursStart,
  sendingHoursEnd,
  sendingDays,
  timezone,
  errors,
  onScheduledStartChange,
  onScheduledEndChange,
  onSendingHoursEnabledChange,
  onSendingHoursStartChange,
  onSendingHoursEndChange,
  onSendingDaysChange,
  onTimezoneChange,
  sendingHoursLabel = "Restrict Sending Hours",
  sendingHoursDescription = "Only send messages during specific hours",
  daysLabel = "Sending Days",
  rateLimitingSlot,
}: ScheduleStepProps) {
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-2">
          <Label htmlFor="scheduled-start">Start Date (Optional)</Label>
          <Input
            id="scheduled-start"
            type="datetime-local"
            value={scheduledStart || ""}
            onChange={(e) => onScheduledStartChange(e.target.value || undefined)}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="scheduled-end">End Date (Optional)</Label>
          <Input
            id="scheduled-end"
            type="datetime-local"
            value={scheduledEnd || ""}
            onChange={(e) => onScheduledEndChange(e.target.value || undefined)}
          />
        </div>
      </div>

      <Separator />

      <div className="space-y-4">
        <div className="flex items-center justify-between p-4 bg-muted/50 rounded-lg">
          <div className="flex items-center gap-2">
            <Clock className="size-4" />
            <div>
              <h4 className="font-medium">{sendingHoursLabel}</h4>
              <p className="text-sm text-muted-foreground">{sendingHoursDescription}</p>
            </div>
          </div>
          <Switch
            aria-label={sendingHoursLabel}
            checked={sendingHoursEnabled}
            onCheckedChange={onSendingHoursEnabledChange}
          />
        </div>

        {sendingHoursEnabled && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="grid grid-cols-3 gap-4 pl-4 border-l-2 border-muted"
          >
            <div className="space-y-2">
              <Label htmlFor="campaign-sending-hours-start">Start Time</Label>
              <Input
                id="campaign-sending-hours-start"
                type="time"
                value={sendingHoursStart}
                onChange={(e) => onSendingHoursStartChange(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="campaign-sending-hours-end">End Time</Label>
              <Input
                id="campaign-sending-hours-end"
                type="time"
                value={sendingHoursEnd}
                onChange={(e) => onSendingHoursEndChange(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="campaign-timezone">Timezone</Label>
              <Select value={timezone} onValueChange={onTimezoneChange}>
                <SelectTrigger id="campaign-timezone">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {TIMEZONES.map((tz) => (
                    <SelectItem key={tz} value={tz}>
                      {tz.replace("_", " ").replace("America/", "")}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </motion.div>
        )}
      </div>

      <div className="space-y-4">
        <h4 className="font-medium flex items-center gap-2">
          <Calendar className="size-4" />
          {daysLabel}
        </h4>
        <div className="flex gap-2">
          {DAYS_OF_WEEK.map((day) => {
            const isSelected = sendingDays.includes(day.value);
            return (
              <Button
                key={day.value}
                variant={isSelected ? "default" : "outline"}
                size="sm"
                className="w-12"
                aria-label={`${day.value} sending`}
                aria-pressed={isSelected}
                onClick={() => {
                  if (isSelected) {
                    onSendingDaysChange(sendingDays.filter((d) => d !== day.value));
                  } else {
                    onSendingDaysChange([...sendingDays, day.value].sort());
                  }
                }}
              >
                {day.label}
              </Button>
            );
          })}
        </div>
        {errors.sending_days && <p className="text-sm text-destructive">{errors.sending_days}</p>}
      </div>

      {rateLimitingSlot && (
        <>
          <Separator />
          {rateLimitingSlot}
        </>
      )}
    </div>
  );
}
