"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Gauge, Loader2, Zap } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import {
  settingsApi,
  type MissedCallTextbackSettings,
  type SpeedToLeadMetrics,
  type SpeedToLeadSettings,
} from "@/lib/api/settings";
import { queryKeys } from "@/lib/query-keys";

function formatSeconds(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${value}s`;
}

export function SpeedToLeadSettingsTab() {
  const workspaceId = useWorkspaceId();

  const { data: settings, isPending: settingsPending } = useQuery({
    queryKey: queryKeys.settings.speedToLead(workspaceId ?? ""),
    queryFn: () => settingsApi.getSpeedToLead(workspaceId!),
    enabled: !!workspaceId,
  });

  const { data: metrics } = useQuery({
    queryKey: queryKeys.settings.speedToLeadMetrics(workspaceId ?? ""),
    queryFn: () => settingsApi.getSpeedToLeadMetrics(workspaceId!),
    enabled: !!workspaceId,
  });

  const { data: textback, isPending: textbackPending } = useQuery({
    queryKey: queryKeys.settings.missedCallTextback(workspaceId ?? ""),
    queryFn: () => settingsApi.getMissedCallTextback(workspaceId!),
    enabled: !!workspaceId,
  });

  if (!workspaceId || settingsPending || textbackPending || !settings || !textback) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="size-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <SpeedToLeadForm
      workspaceId={workspaceId}
      settings={settings}
      textback={textback}
      metrics={metrics}
    />
  );
}

interface FormProps {
  workspaceId: string;
  settings: SpeedToLeadSettings;
  textback: MissedCallTextbackSettings;
  metrics: SpeedToLeadMetrics | undefined;
}

function SpeedToLeadForm({ workspaceId, settings, textback, metrics }: FormProps) {
  const queryClient = useQueryClient();
  // Initialised once from loaded data; no effect-based mirroring needed.
  const [slaSeconds, setSlaSeconds] = useState<number>(settings.sla_seconds);
  const [template, setTemplate] = useState<string>(textback.template);

  const slaMutation = useMutation({
    mutationFn: (data: Parameters<typeof settingsApi.updateSpeedToLead>[1]) =>
      settingsApi.updateSpeedToLead(workspaceId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.settings.speedToLead(workspaceId),
      });
      queryClient.invalidateQueries({
        queryKey: queryKeys.settings.speedToLeadMetrics(workspaceId),
      });
    },
  });

  const textbackMutation = useMutation({
    mutationFn: (
      data: Parameters<typeof settingsApi.updateMissedCallTextback>[1],
    ) => settingsApi.updateMissedCallTextback(workspaceId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.settings.missedCallTextback(workspaceId),
      });
    },
  });

  const pct = metrics?.pct_within_sla;

  return (
    <div className="space-y-6">
      {/* Live first-response metrics */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Gauge className="size-5" /> First-response performance
          </CardTitle>
          <CardDescription>
            Time-to-first-reply for new inbound leads over the last{" "}
            {metrics?.window_days ?? settings.badge_window_days} days.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <div>
            <p className="text-2xl font-bold">
              {pct === null || pct === undefined ? "—" : `${pct}%`}
            </p>
            <p className="text-sm text-muted-foreground">
              within {metrics?.sla_seconds ?? settings.sla_seconds}s
            </p>
          </div>
          <div>
            <p className="text-2xl font-bold">
              {formatSeconds(metrics?.median_response_seconds)}
            </p>
            <p className="text-sm text-muted-foreground">median</p>
          </div>
          <div>
            <p className="text-2xl font-bold">
              {formatSeconds(metrics?.fastest_response_seconds)}
            </p>
            <p className="text-sm text-muted-foreground">fastest</p>
          </div>
          <div>
            <p className="text-2xl font-bold">{metrics?.leads_measured ?? 0}</p>
            <p className="text-sm text-muted-foreground">leads measured</p>
          </div>
        </CardContent>
      </Card>

      {/* SLA configuration */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Zap className="size-5" /> Speed-to-lead SLA
          </CardTitle>
          <CardDescription>
            Set your first-response target and how misses are handled.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label>Enable SLA tracking</Label>
              <p className="text-sm text-muted-foreground">
                Measure time-to-first-response on every new lead.
              </p>
            </div>
            <Switch
              checked={settings.enabled}
              onCheckedChange={(checked) =>
                slaMutation.mutate({ enabled: checked })
              }
              disabled={slaMutation.isPending}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="sla-seconds">Response target (seconds)</Label>
            <div className="flex items-center gap-3">
              <Input
                id="sla-seconds"
                type="number"
                min={5}
                max={3600}
                value={slaSeconds}
                onChange={(e) => setSlaSeconds(Number(e.target.value))}
                className="w-32"
              />
              <Button
                onClick={() => slaMutation.mutate({ sla_seconds: slaSeconds })}
                disabled={
                  slaMutation.isPending || slaSeconds === settings.sla_seconds
                }
              >
                Save target
              </Button>
            </div>
          </div>

          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label>Alert on misses</Label>
              <p className="text-sm text-muted-foreground">
                Notify the team when a lead waits longer than the target.
              </p>
            </div>
            <Switch
              checked={settings.alert_enabled}
              onCheckedChange={(checked) =>
                slaMutation.mutate({ alert_enabled: checked })
              }
              disabled={slaMutation.isPending}
            />
          </div>

          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label>Public proof badge</Label>
              <p className="text-sm text-muted-foreground">
                Show your answered-within-target stat on the lead-form widget.
              </p>
            </div>
            <Switch
              checked={settings.badge_enabled}
              onCheckedChange={(checked) =>
                slaMutation.mutate({ badge_enabled: checked })
              }
              disabled={slaMutation.isPending}
            />
          </div>
        </CardContent>
      </Card>

      {/* Missed-call text-back */}
      <Card>
        <CardHeader>
          <CardTitle>Missed-call text-back</CardTitle>
          <CardDescription>
            Automatically text callers back when an inbound call goes unanswered.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label>Enable text-back</Label>
              <p className="text-sm text-muted-foreground">
                Send an instant SMS to capture the missed lead.
              </p>
            </div>
            <Switch
              checked={textback.enabled}
              onCheckedChange={(checked) =>
                textbackMutation.mutate({ enabled: checked })
              }
              disabled={textbackMutation.isPending}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="textback-template">Message</Label>
            <Textarea
              id="textback-template"
              value={template}
              maxLength={1000}
              rows={3}
              onChange={(e) => setTemplate(e.target.value)}
              placeholder="Sorry we missed you — want me to book you in?"
            />
            <p className="text-xs text-muted-foreground">
              You can use {"{first_name}"} and {"{company_name}"} placeholders.
            </p>
            <Button
              onClick={() => textbackMutation.mutate({ template })}
              disabled={
                textbackMutation.isPending || template === textback.template
              }
            >
              Save message
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
