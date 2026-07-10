"use client";

import { CalendarClock, Loader2 } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { useUpdateAgent } from "@/hooks/useAgents";
import type {
  Agent,
  AgentScheduleConfig,
  ScheduleWeekday,
  ScheduleWindow,
} from "@/types/agent";

interface ScheduleConfigSectionProps {
  agent: Agent;
}

const WEEKDAYS: { key: ScheduleWeekday; label: string }[] = [
  { key: "mon", label: "Monday" },
  { key: "tue", label: "Tuesday" },
  { key: "wed", label: "Wednesday" },
  { key: "thu", label: "Thursday" },
  { key: "fri", label: "Friday" },
  { key: "sat", label: "Saturday" },
  { key: "sun", label: "Sunday" },
];

const DEFAULT_WINDOW: ScheduleWindow = ["09:00", "17:00"];

type DayState = { enabled: boolean; start: string; end: string };

function toDayState(windows: ScheduleWindow[] | undefined): DayState {
  const first = windows && windows.length > 0 ? windows[0] : null;
  return first
    ? { enabled: true, start: first[0], end: first[1] }
    : { enabled: false, start: DEFAULT_WINDOW[0], end: DEFAULT_WINDOW[1] };
}

/**
 * Weekly working-hours editor backed by ``agent.schedule_config``. Feeds the
 * Google Calendar availability engine (Cal.com stored this server-side; Google
 * gives only free/busy, so we store it here). Saves directly via the agents API.
 */
export function ScheduleConfigSection({ agent }: ScheduleConfigSectionProps) {
  const updateAgent = useUpdateAgent(agent.workspace_id);
  const config = agent.schedule_config ?? {};

  const [timezone, setTimezone] = useState(config.timezone ?? "America/New_York");
  const [slotDuration, setSlotDuration] = useState(String(config.slot_duration_minutes ?? 30));
  const [bufferAfter, setBufferAfter] = useState(String(config.buffer_after_minutes ?? 0));
  const [minNotice, setMinNotice] = useState(String(config.min_notice_minutes ?? 120));
  const [horizon, setHorizon] = useState(String(config.max_horizon_days ?? 30));

  const [days, setDays] = useState<Record<ScheduleWeekday, DayState>>(() => {
    const weekly = config.weekly_hours ?? {};
    return WEEKDAYS.reduce(
      (acc, { key }) => {
        acc[key] = toDayState(weekly[key]);
        return acc;
      },
      {} as Record<ScheduleWeekday, DayState>,
    );
  });

  const updateDay = (key: ScheduleWeekday, patch: Partial<DayState>) => {
    setDays((prev) => ({ ...prev, [key]: { ...prev[key], ...patch } }));
  };

  const buildConfig = (): AgentScheduleConfig => {
    const weekly_hours: Partial<Record<ScheduleWeekday, ScheduleWindow[]>> = {};
    for (const { key } of WEEKDAYS) {
      const day = days[key];
      weekly_hours[key] = day.enabled ? [[day.start, day.end]] : [];
    }
    return {
      timezone,
      slot_duration_minutes: Number(slotDuration) || 30,
      buffer_after_minutes: Number(bufferAfter) || 0,
      min_notice_minutes: Number(minNotice) || 0,
      max_horizon_days: Number(horizon) || 30,
      weekly_hours,
    };
  };

  const handleSave = () => {
    updateAgent.mutate(
      { id: agent.id, data: { schedule_config: buildConfig() } },
      {
        onSuccess: () => toast.success("Booking schedule saved"),
        onError: () => toast.error("Failed to save booking schedule"),
      },
    );
  };

  const numberFields = useMemo(
    () => [
      { label: "Slot length (min)", value: slotDuration, set: setSlotDuration },
      { label: "Buffer after (min)", value: bufferAfter, set: setBufferAfter },
      { label: "Min notice (min)", value: minNotice, set: setMinNotice },
      { label: "Booking horizon (days)", value: horizon, set: setHorizon },
    ],
    [slotDuration, bufferAfter, minNotice, horizon],
  );

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-sm font-medium flex items-center gap-2">
          <CalendarClock className="h-4 w-4" />
          Booking Schedule (Google Calendar)
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-muted-foreground">
          Working hours and booking rules the AI uses to compute available slots when this
          workspace books through Google Calendar. Ignored on the Cal.com path.
        </p>

        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="schedule-timezone">Timezone (IANA)</Label>
            <Input
              id="schedule-timezone"
              value={timezone}
              onChange={(e) => setTimezone(e.target.value)}
              placeholder="America/New_York"
            />
          </div>
          {numberFields.map((f) => (
            <div key={f.label} className="space-y-1.5">
              <Label>{f.label}</Label>
              <Input
                type="number"
                min={0}
                value={f.value}
                onChange={(e) => f.set(e.target.value)}
              />
            </div>
          ))}
        </div>

        <div className="space-y-2">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Weekly hours
          </p>
          {WEEKDAYS.map(({ key, label }) => {
            const day = days[key];
            return (
              <div key={key} className="flex flex-wrap items-center gap-3 rounded-md border p-2.5">
                <div className="flex w-32 items-center gap-2">
                  <Switch
                    checked={day.enabled}
                    onCheckedChange={(checked) => updateDay(key, { enabled: checked })}
                    aria-label={`Toggle ${label}`}
                  />
                  <span className="text-sm font-medium">{label}</span>
                </div>
                {day.enabled ? (
                  <div className="flex items-center gap-2">
                    <Input
                      type="time"
                      value={day.start}
                      onChange={(e) => updateDay(key, { start: e.target.value })}
                      className="w-32"
                    />
                    <span className="text-muted-foreground">to</span>
                    <Input
                      type="time"
                      value={day.end}
                      onChange={(e) => updateDay(key, { end: e.target.value })}
                      className="w-32"
                    />
                  </div>
                ) : (
                  <span className="text-sm text-muted-foreground">Closed</span>
                )}
              </div>
            );
          })}
        </div>

        <Button type="button" size="sm" onClick={handleSave} disabled={updateAgent.isPending}>
          {updateAgent.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          Save schedule
        </Button>
      </CardContent>
    </Card>
  );
}
