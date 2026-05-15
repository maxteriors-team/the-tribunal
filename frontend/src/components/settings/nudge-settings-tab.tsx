"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Info } from "lucide-react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { nudgesApi } from "@/lib/api/nudges";
import { useWorkspaceId } from "@/hooks/use-workspace-id";
import { queryKeys } from "@/lib/query-keys";
import type { UpdateNudgeSettings, NudgeType } from "@/types/nudge";

const NUDGE_TYPE_OPTIONS: { type: NudgeType; label: string; emoji: string }[] = [
  { type: "birthday", label: "Birthdays", emoji: "🎂" },
  { type: "anniversary", label: "Anniversaries", emoji: "💍" },
  { type: "custom", label: "Custom Dates", emoji: "📅" },
  { type: "cooling", label: "Relationship Cooling", emoji: "🔄" },
  { type: "follow_up", label: "Follow-ups", emoji: "📋" },
];

export function NudgeSettingsTab() {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();

  const { data: settings, isPending } = useQuery({
    queryKey: queryKeys.nudges.settings(workspaceId ?? ""),
    queryFn: () => nudgesApi.getSettings(workspaceId!),
    enabled: !!workspaceId,
  });

  const mutation = useMutation({
    mutationFn: (data: UpdateNudgeSettings) =>
      nudgesApi.updateSettings(workspaceId!, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.nudges.settings(workspaceId ?? "") });
    },
  });

  const update = (data: UpdateNudgeSettings) => {
    mutation.mutate(data);
  };

  const toggleNudgeType = (type: NudgeType, checked: boolean) => {
    const current = settings?.nudge_types ?? [];
    const updated = checked
      ? [...current, type]
      : current.filter((t) => t !== type);
    update({ nudge_types: updated });
  };

  const toggleChannel = (channel: string, checked: boolean) => {
    const current = settings?.delivery_channels ?? [];
    const updated = checked
      ? [...current, channel]
      : current.filter((c) => c !== channel);
    update({ delivery_channels: updated });
  };

  if (isPending) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="size-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const enabled = settings?.enabled ?? false;
  const hasSms = settings?.delivery_channels?.includes("sms");

  return (
    <div className="space-y-6">
      {/* Master Toggle */}
      <Card>
        <CardHeader>
          <CardTitle>Nudge System</CardTitle>
          <CardDescription>
            Get SMS and push reminders about contact birthdays, anniversaries,
            and follow-ups
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label>Enable Nudges</Label>
              <p className="text-sm text-muted-foreground">
                Turn the nudge system on or off
              </p>
            </div>
            <Switch
              checked={enabled}
              onCheckedChange={(checked) => update({ enabled: checked })}
              disabled={mutation.isPending}
            />
          </div>
        </CardContent>
      </Card>

      {/* Timing */}
      {enabled && (
        <Card>
          <CardHeader>
            <CardTitle>Timing</CardTitle>
            <CardDescription>
              Control when nudges are generated and sent
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="space-y-2">
              <Label htmlFor="lead-days">Days before event to send reminder</Label>
              <Input
                id="lead-days"
                type="number"
                min={1}
                max={30}
                className="w-24"
                value={settings?.lead_days ?? 3}
                onChange={(e) => {
                  const val = parseInt(e.target.value, 10);
                  if (val >= 1 && val <= 30) update({ lead_days: val });
                }}
                disabled={mutation.isPending}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="cooling-days">
                Days of no contact before &quot;going cold&quot; reminder
              </Label>
              <Input
                id="cooling-days"
                type="number"
                min={7}
                max={365}
                className="w-24"
                value={settings?.cooling_days ?? 30}
                onChange={(e) => {
                  const val = parseInt(e.target.value, 10);
                  if (val >= 7 && val <= 365) update({ cooling_days: val });
                }}
                disabled={mutation.isPending}
              />
            </div>
          </CardContent>
        </Card>
      )}

      {/* Nudge Types */}
      {enabled && (
        <Card>
          <CardHeader>
            <CardTitle>Nudge Types</CardTitle>
            <CardDescription>
              Choose which types of nudges you want to receive
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {NUDGE_TYPE_OPTIONS.map((opt) => (
              <div key={opt.type} className="flex items-center justify-between">
                <div className="space-y-0.5">
                  <Label>
                    {opt.emoji} {opt.label}
                  </Label>
                </div>
                <Switch
                  checked={settings?.nudge_types?.includes(opt.type) ?? false}
                  onCheckedChange={(checked) =>
                    toggleNudgeType(opt.type, checked)
                  }
                  disabled={mutation.isPending}
                />
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Delivery Channels */}
      {enabled && (
        <Card>
          <CardHeader>
            <CardTitle>Delivery Channels</CardTitle>
            <CardDescription>
              How you want to receive nudge notifications
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between">
              <div className="space-y-0.5">
                <Label>SMS</Label>
                <p className="text-sm text-muted-foreground">
                  Requires a phone number in your profile
                </p>
              </div>
              <Switch
                checked={hasSms ?? false}
                onCheckedChange={(checked) => toggleChannel("sms", checked)}
                disabled={mutation.isPending}
              />
            </div>
            <div className="flex items-center justify-between">
              <div className="space-y-0.5">
                <Label>Push Notifications</Label>
                <p className="text-sm text-muted-foreground">
                  Real-time alerts in your browser
                </p>
              </div>
              <Switch
                checked={
                  settings?.delivery_channels?.includes("push") ?? false
                }
                onCheckedChange={(checked) => toggleChannel("push", checked)}
                disabled={mutation.isPending}
              />
            </div>
            {hasSms && (
              <Alert>
                <Info className="size-4" />
                <AlertDescription>
                  Make sure you have a phone number set in your{" "}
                  <span className="font-medium underline">Profile</span>{" "}
                  settings tab to receive SMS nudges.
                </AlertDescription>
              </Alert>
            )}
          </CardContent>
        </Card>
      )}

      {/* Quiet Hours */}
      {enabled && (
        <Card>
          <CardHeader>
            <CardTitle>Quiet Hours</CardTitle>
            <CardDescription>
              No SMS notifications during these hours
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="quiet-start">Start</Label>
                <Input
                  id="quiet-start"
                  type="time"
                  value={settings?.quiet_hours_start ?? "22:00"}
                  onChange={(e) =>
                    update({ quiet_hours_start: e.target.value })
                  }
                  disabled={mutation.isPending}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="quiet-end">End</Label>
                <Input
                  id="quiet-end"
                  type="time"
                  value={settings?.quiet_hours_end ?? "08:00"}
                  onChange={(e) =>
                    update({ quiet_hours_end: e.target.value })
                  }
                  disabled={mutation.isPending}
                />
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
