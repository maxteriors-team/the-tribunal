"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, Loader2, MessageSquareText, PhoneCall, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useSettingsSaveMutation } from "@/hooks/useSettingsSaveMutation";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { messageTemplatesApi } from "@/lib/api/message-templates";
import {
  type QuoteFollowupChannel,
  type QuoteFollowupSettings,
  type QuoteFollowupTouch,
  settingsApi,
} from "@/lib/api/settings";
import { queryKeys } from "@/lib/query-keys";
import type { MessageTemplate } from "@/types";

const MAX_OFFSET_DAYS = 14;
const NONE_TEMPLATE = "none";

export function QuoteFollowupSettingsTab() {
  const workspaceId = useWorkspaceId();

  const { data: settings, isPending: settingsPending } = useQuery({
    queryKey: queryKeys.settings.quoteFollowup(workspaceId ?? ""),
    queryFn: () => settingsApi.getQuoteFollowup(workspaceId!),
    enabled: !!workspaceId,
  });
  const { data: templatesPage, isPending: templatesPending } = useQuery({
    queryKey: queryKeys.messageTemplates.list(workspaceId ?? "", {
      page: 1,
      page_size: 100,
    }),
    queryFn: () => messageTemplatesApi.list(workspaceId!, { page: 1, page_size: 100 }),
    enabled: !!workspaceId,
  });

  if (!workspaceId || settingsPending || templatesPending || !settings || !templatesPage) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="size-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <QuoteFollowupForm
      workspaceId={workspaceId}
      initialSettings={settings}
      templates={templatesPage.items}
    />
  );
}

interface QuoteFollowupFormProps {
  workspaceId: string;
  initialSettings: QuoteFollowupSettings;
  templates: MessageTemplate[];
}

function QuoteFollowupForm({ workspaceId, initialSettings, templates }: QuoteFollowupFormProps) {
  const queryClient = useQueryClient();
  const [enabled, setEnabled] = useState(initialSettings.enabled);
  const [threshold, setThreshold] = useState(initialSettings.high_value_threshold);
  const [quietStart, setQuietStart] = useState(
    initialSettings.quiet_hours_start?.slice(0, 5) ?? "",
  );
  const [quietEnd, setQuietEnd] = useState(initialSettings.quiet_hours_end?.slice(0, 5) ?? "");
  const [timezone, setTimezone] = useState(initialSettings.timezone ?? "");
  const [touches, setTouches] = useState<QuoteFollowupTouch[]>(
    initialSettings.touches.map((touch) => ({ ...touch })),
  );

  const mutation = useSettingsSaveMutation({
    mutationFn: (data: QuoteFollowupSettings) => settingsApi.updateQuoteFollowup(workspaceId, data),
    successMessage: "Estimate follow-up settings are up to date.",
    errorMessage:
      "We couldn't save estimate follow-up settings. Check your connection and try again.",
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.settings.quoteFollowup(workspaceId),
      });
    },
  });

  const updateTouch = (index: number, patch: Partial<QuoteFollowupTouch>) => {
    setTouches((current) =>
      current.map((touch, touchIndex) => {
        if (touchIndex !== index) return touch;
        const updated = { ...touch, ...patch };
        if (updated.channel === "call") updated.template_id = null;
        return updated;
      }),
    );
  };

  const addTouch = () => {
    const usedOffsets = new Set(touches.map((touch) => touch.offset_days));
    const offset = Array.from({ length: MAX_OFFSET_DAYS + 1 }, (_, day) => day).find(
      (day) => !usedOffsets.has(day),
    );
    if (offset === undefined) {
      toast.error("Every day from 0 through 14 already has a touch");
      return;
    }
    setTouches((current) => [
      ...current,
      { offset_days: offset, channel: "call", template_id: null },
    ]);
  };

  const save = () => {
    const sortedTouches = [...touches].sort((left, right) => left.offset_days - right.offset_days);
    const offsets = sortedTouches.map((touch) => touch.offset_days);
    if (new Set(offsets).size !== offsets.length) {
      toast.error("Each touch needs a different day");
      return;
    }
    if (!sortedTouches.some((touch) => touch.channel === "call")) {
      toast.error("Add at least one human call task");
      return;
    }
    if (!sortedTouches.some((touch) => touch.channel === "sms" || touch.channel === "email")) {
      toast.error("Add at least one SMS or email touch");
      return;
    }
    if (enabled && sortedTouches.some((touch) => touch.channel !== "call" && !touch.template_id)) {
      toast.error("Choose a saved template for every SMS and email touch");
      return;
    }
    if ((quietStart && !quietEnd) || (!quietStart && quietEnd)) {
      toast.error("Set both quiet-hour times or clear both");
      return;
    }
    if (!Number.isFinite(threshold) || threshold < 0) {
      toast.error("Enter a valid high-value threshold");
      return;
    }

    setTouches(sortedTouches);
    mutation.mutate({
      enabled,
      high_value_threshold: threshold,
      quiet_hours_start: quietStart || null,
      quiet_hours_end: quietEnd || null,
      timezone: timezone.trim() || null,
      touches: sortedTouches,
    });
  };

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <MessageSquareText className="size-5" /> Estimate close-rate cadence
          </CardTitle>
          <CardDescription>
            Follow up while a sent quote is still fresh. The sequence stops on a decision, reply,
            opt-out, or booked appointment.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="flex items-center justify-between gap-4">
            <div className="space-y-0.5">
              <Label htmlFor="quote-followup-enabled">Enable post-estimate follow-up</Label>
              <p className="text-sm text-muted-foreground">
                Run the configured touches from the quote&apos;s first sent date.
              </p>
            </div>
            <Switch
              id="quote-followup-enabled"
              checked={enabled}
              onCheckedChange={setEnabled}
              disabled={mutation.isPending}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="quote-followup-threshold">High-value quote threshold</Label>
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground">$</span>
              <Input
                id="quote-followup-threshold"
                className="w-40"
                type="number"
                min={0}
                step={100}
                value={threshold}
                onChange={(event) => setThreshold(Number(event.target.value))}
              />
            </div>
            <p className="text-sm text-muted-foreground">
              SMS steps at or above this value become human call tasks instead.
            </p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <PhoneCall className="size-5" /> First 14 days
          </CardTitle>
          <CardDescription>
            Mix automation with real conversations. Day 15 and later are excluded so this cadence
            cannot collide with 30/60/90-day quote revival.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {templates.length === 0 && (
            <Alert>
              <AlertDescription className="flex flex-wrap items-center justify-between gap-3">
                <span>Save at least one message template before enabling SMS or email.</span>
                <Button asChild size="sm" variant="outline">
                  <Link href="/experiments">
                    Manage templates <ExternalLink className="ml-2 size-3.5" />
                  </Link>
                </Button>
              </AlertDescription>
            </Alert>
          )}

          {touches.map((touch, index) => (
            <TouchRow
              key={`${index}-${touch.offset_days}`}
              index={index}
              touch={touch}
              templates={templates}
              canRemove={touches.length > 3}
              disabled={mutation.isPending}
              onChange={(patch) => updateTouch(index, patch)}
              onRemove={() =>
                setTouches((current) => current.filter((_, touchIndex) => touchIndex !== index))
              }
            />
          ))}

          <Button
            type="button"
            variant="outline"
            onClick={addTouch}
            disabled={mutation.isPending || touches.length >= 8}
          >
            <Plus className="mr-2 size-4" /> Add touch
          </Button>

          <p className="text-xs text-muted-foreground">
            Template placeholders: {"{first_name}"}, {"{last_name}"}, {"{quote_number}"},{" "}
            {"{quote_total}"}, {"{proposal_url}"}, and {"{company_name}"}.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Quiet hours</CardTitle>
          <CardDescription>
            Automated customer messages wait until outside this local window. Human call tasks can
            still be queued for the team.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-3">
            <div className="space-y-2">
              <Label htmlFor="quote-followup-quiet-start">Start</Label>
              <Input
                id="quote-followup-quiet-start"
                type="time"
                value={quietStart}
                onChange={(event) => setQuietStart(event.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="quote-followup-quiet-end">End</Label>
              <Input
                id="quote-followup-quiet-end"
                type="time"
                value={quietEnd}
                onChange={(event) => setQuietEnd(event.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="quote-followup-timezone">Timezone</Label>
              <Input
                id="quote-followup-timezone"
                value={timezone}
                onChange={(event) => setTimezone(event.target.value)}
                placeholder="Workspace timezone"
              />
            </div>
          </div>

          <Button onClick={save} disabled={mutation.isPending}>
            {mutation.isPending && <Loader2 className="mr-2 size-4 animate-spin" />}
            Save cadence
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}

interface TouchRowProps {
  index: number;
  touch: QuoteFollowupTouch;
  templates: MessageTemplate[];
  canRemove: boolean;
  disabled: boolean;
  onChange: (patch: Partial<QuoteFollowupTouch>) => void;
  onRemove: () => void;
}

function TouchRow({
  index,
  touch,
  templates,
  canRemove,
  disabled,
  onChange,
  onRemove,
}: TouchRowProps) {
  const selectedTemplate = templates.find((template) => template.id === touch.template_id);

  return (
    <div className="rounded-lg border p-4">
      <div className="grid items-end gap-3 md:grid-cols-[100px_150px_minmax(220px,1fr)_auto]">
        <div className="space-y-2">
          <Label htmlFor={`quote-touch-day-${index}`}>Day</Label>
          <Input
            id={`quote-touch-day-${index}`}
            type="number"
            min={0}
            max={MAX_OFFSET_DAYS}
            value={touch.offset_days}
            disabled={disabled}
            onChange={(event) => onChange({ offset_days: Number(event.target.value) })}
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor={`quote-touch-channel-${index}`}>Channel</Label>
          <Select
            value={touch.channel}
            disabled={disabled}
            onValueChange={(value) => onChange({ channel: value as QuoteFollowupChannel })}
          >
            <SelectTrigger id={`quote-touch-channel-${index}`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="sms">SMS</SelectItem>
              <SelectItem value="email">Email</SelectItem>
              <SelectItem value="call">Human call task</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-2">
          <Label htmlFor={`quote-touch-template-${index}`}>Saved message template</Label>
          <Select
            value={touch.template_id ?? NONE_TEMPLATE}
            disabled={disabled || touch.channel === "call"}
            onValueChange={(value) =>
              onChange({ template_id: value === NONE_TEMPLATE ? null : value })
            }
          >
            <SelectTrigger id={`quote-touch-template-${index}`}>
              <SelectValue
                placeholder={touch.channel === "call" ? "Not needed for calls" : "Choose template"}
              />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NONE_TEMPLATE}>Choose template</SelectItem>
              {templates.map((template) => (
                <SelectItem key={template.id} value={template.id}>
                  {template.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <Button
          type="button"
          size="icon"
          variant="ghost"
          aria-label={`Remove day ${touch.offset_days} touch`}
          onClick={onRemove}
          disabled={disabled || !canRemove}
        >
          <Trash2 className="size-4" />
        </Button>
      </div>

      {selectedTemplate && touch.channel !== "call" && (
        <p className="mt-3 line-clamp-2 text-xs text-muted-foreground">
          {selectedTemplate.message_template}
        </p>
      )}
    </div>
  );
}
