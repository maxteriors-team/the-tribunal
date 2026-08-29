"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, History, Loader2, Plus, Trash2, Wallet } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { QuoteExpirySettingsCard } from "@/components/settings/quote-expiry-settings-card";
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
  type QuoteRevivalChannel,
  type QuoteRevivalSettings,
  type QuoteRevivalTouch,
  settingsApi,
} from "@/lib/api/settings";
import { queryKeys } from "@/lib/query-keys";
import type { MessageTemplate } from "@/types";

// Day 0-14 belongs to the post-estimate cadence; revival may never reach back
// into that window, which is the same rail the API enforces.
const MIN_OFFSET_DAYS = 15;
const MAX_OFFSET_DAYS = 365;
const MAX_TOUCHES = 6;
const NONE_TEMPLATE = "none";

export function QuoteRevivalSettingsTab() {
  const workspaceId = useWorkspaceId();

  const { data: settings, isPending: settingsPending } = useQuery({
    queryKey: queryKeys.settings.quoteRevival(workspaceId ?? ""),
    queryFn: () => settingsApi.getQuoteRevival(workspaceId!),
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
    <QuoteRevivalForm
      workspaceId={workspaceId}
      initialSettings={settings}
      templates={templatesPage.items}
    />
  );
}

interface QuoteRevivalFormProps {
  workspaceId: string;
  initialSettings: QuoteRevivalSettings;
  templates: MessageTemplate[];
}

function QuoteRevivalForm({ workspaceId, initialSettings, templates }: QuoteRevivalFormProps) {
  const queryClient = useQueryClient();
  const [enabled, setEnabled] = useState(initialSettings.enabled);
  const [threshold, setThreshold] = useState(initialSettings.high_value_threshold);
  const [maxTouches, setMaxTouches] = useState(initialSettings.max_touches);
  const [quietStart, setQuietStart] = useState(
    initialSettings.quiet_hours_start?.slice(0, 5) ?? "",
  );
  const [quietEnd, setQuietEnd] = useState(initialSettings.quiet_hours_end?.slice(0, 5) ?? "");
  const [timezone, setTimezone] = useState(initialSettings.timezone ?? "");
  const [touches, setTouches] = useState<QuoteRevivalTouch[]>(
    initialSettings.touches.map((touch) => ({ ...touch })),
  );

  const mutation = useSettingsSaveMutation({
    mutationFn: (data: QuoteRevivalSettings) => settingsApi.updateQuoteRevival(workspaceId, data),
    successMessage: "Quote revival settings are up to date.",
    errorMessage: "We couldn't save quote revival settings. Check your connection and try again.",
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.settings.quoteRevival(workspaceId),
      });
    },
  });

  const updateTouch = (index: number, patch: Partial<QuoteRevivalTouch>) => {
    setTouches((current) =>
      current.map((touch, touchIndex) => {
        if (touchIndex !== index) return touch;
        const updated = { ...touch, ...patch };
        if (updated.channel === "call") {
          updated.template_id = null;
          updated.high_value_template_id = null;
        }
        return updated;
      }),
    );
  };

  const addTouch = () => {
    const lastOffset = touches.length ? Math.max(...touches.map((touch) => touch.offset_days)) : 0;
    const offset = Math.min(Math.max(lastOffset + 30, MIN_OFFSET_DAYS), MAX_OFFSET_DAYS);
    if (touches.some((touch) => touch.offset_days === offset)) {
      toast.error("Pick a different day for the next touch");
      return;
    }
    setTouches((current) => [
      ...current,
      {
        offset_days: offset,
        channel: "sms",
        template_id: null,
        high_value_template_id: null,
      },
    ]);
  };

  const save = () => {
    const sortedTouches = [...touches].sort((left, right) => left.offset_days - right.offset_days);
    const offsets = sortedTouches.map((touch) => touch.offset_days);
    if (new Set(offsets).size !== offsets.length) {
      toast.error("Each touch needs a different day");
      return;
    }
    if (offsets.some((offset) => offset < MIN_OFFSET_DAYS)) {
      toast.error(
        `Revival starts at day ${MIN_OFFSET_DAYS} — earlier days belong to estimate follow-up`,
      );
      return;
    }
    if (!sortedTouches.some((touch) => touch.channel !== "call")) {
      toast.error("Add at least one SMS or email touch");
      return;
    }
    // Only the touches that can actually run need copy, matching the API.
    const executable = sortedTouches.slice(0, maxTouches);
    if (enabled && executable.some((touch) => touch.channel !== "call" && !touch.template_id)) {
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
      max_touches: maxTouches,
      quiet_hours_start: quietStart || null,
      quiet_hours_end: quietEnd || null,
      timezone: timezone.trim() || null,
      touches: sortedTouches,
    });
  };

  return (
    <div className="space-y-6">
      <QuoteExpirySettingsCard />
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <History className="size-5" /> Unsold quote revival
          </CardTitle>
          <CardDescription>
            Work quotes that were issued and went quiet. The ladder stops on a decision, a reply, an
            opt-out, or a booked appointment.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="flex items-center justify-between gap-4">
            <div className="space-y-0.5">
              <Label htmlFor="quote-revival-enabled">Enable unsold quote revival</Label>
              <p className="text-sm text-muted-foreground">
                Runs from the quote&apos;s issue date, long after estimate follow-up has ended.
              </p>
            </div>
            <Switch
              id="quote-revival-enabled"
              checked={enabled}
              onCheckedChange={setEnabled}
              disabled={mutation.isPending}
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="quote-revival-threshold">High-value quote threshold</Label>
              <div className="flex items-center gap-2">
                <span className="text-sm text-muted-foreground">$</span>
                <Input
                  id="quote-revival-threshold"
                  className="w-40"
                  type="number"
                  min={0}
                  step={100}
                  value={threshold}
                  onChange={(event) => setThreshold(Number(event.target.value))}
                />
              </div>
              <p className="text-sm text-muted-foreground">
                Quotes at or above this total use the high-value template.
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="quote-revival-max-touches">Maximum touches</Label>
              <Input
                id="quote-revival-max-touches"
                className="w-40"
                type="number"
                min={1}
                max={MAX_TOUCHES}
                value={maxTouches}
                onChange={(event) => setMaxTouches(Number(event.target.value))}
              />
              <p className="text-sm text-muted-foreground">
                Hard stop per quote, however many steps are configured below.
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Wallet className="size-5" /> The 30/60/90 ladder
          </CardTitle>
          <CardDescription>
            Day {MIN_OFFSET_DAYS} is the earliest legal step, so this ladder can never collide with
            the first-14-days estimate cadence.
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
              retired={index >= maxTouches}
              canRemove={touches.length > 1}
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
            disabled={mutation.isPending || touches.length >= MAX_TOUCHES}
          >
            <Plus className="mr-2 size-4" /> Add touch
          </Button>

          <p className="text-xs text-muted-foreground">
            Template placeholders: {"{first_name}"}, {"{last_name}"}, {"{quote_number}"},{" "}
            {"{quote_total}"}, {"{proposal_url}"}, {"{company_name}"}, {"{days_since_quote}"}, and{" "}
            {"{expiry_date}"} — enough to write price-validity, seasonal-slot, or financing copy.
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
              <Label htmlFor="quote-revival-quiet-start">Start</Label>
              <Input
                id="quote-revival-quiet-start"
                type="time"
                value={quietStart}
                onChange={(event) => setQuietStart(event.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="quote-revival-quiet-end">End</Label>
              <Input
                id="quote-revival-quiet-end"
                type="time"
                value={quietEnd}
                onChange={(event) => setQuietEnd(event.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="quote-revival-timezone">Timezone</Label>
              <Input
                id="quote-revival-timezone"
                value={timezone}
                onChange={(event) => setTimezone(event.target.value)}
                placeholder="Workspace timezone"
              />
            </div>
          </div>

          <Button onClick={save} disabled={mutation.isPending}>
            {mutation.isPending && <Loader2 className="mr-2 size-4 animate-spin" />}
            Save revival ladder
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}

interface TouchRowProps {
  index: number;
  touch: QuoteRevivalTouch;
  templates: MessageTemplate[];
  retired: boolean;
  canRemove: boolean;
  disabled: boolean;
  onChange: (patch: Partial<QuoteRevivalTouch>) => void;
  onRemove: () => void;
}

function TouchRow({
  index,
  touch,
  templates,
  retired,
  canRemove,
  disabled,
  onChange,
  onRemove,
}: TouchRowProps) {
  const isCall = touch.channel === "call";

  return (
    <div className={`rounded-lg border p-4 ${retired ? "opacity-60" : ""}`}>
      <div className="grid items-end gap-3 md:grid-cols-[100px_150px_minmax(180px,1fr)_minmax(180px,1fr)_auto]">
        <div className="space-y-2">
          <Label htmlFor={`revival-touch-day-${index}`}>Day</Label>
          <Input
            id={`revival-touch-day-${index}`}
            type="number"
            min={MIN_OFFSET_DAYS}
            max={MAX_OFFSET_DAYS}
            value={touch.offset_days}
            disabled={disabled}
            onChange={(event) => onChange({ offset_days: Number(event.target.value) })}
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor={`quote-revival-channel-${index}`}>Channel</Label>
          <Select
            value={touch.channel}
            disabled={disabled}
            onValueChange={(value) => onChange({ channel: value as QuoteRevivalChannel })}
          >
            <SelectTrigger id={`quote-revival-channel-${index}`}>
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
          <Label htmlFor={`quote-revival-template-${index}`}>Standard template</Label>
          <TemplateSelect
            id={`quote-revival-template-${index}`}
            value={touch.template_id}
            templates={templates}
            disabled={disabled || isCall}
            placeholder={isCall ? "Not needed for calls" : "Choose template"}
            onChange={(template_id) => onChange({ template_id })}
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor={`quote-revival-high-value-template-${index}`}>High-value template</Label>
          <TemplateSelect
            id={`quote-revival-high-value-template-${index}`}
            value={touch.high_value_template_id}
            templates={templates}
            disabled={disabled || isCall}
            placeholder={isCall ? "Not needed for calls" : "Same as standard"}
            onChange={(high_value_template_id) => onChange({ high_value_template_id })}
          />
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

      {retired && (
        <p className="mt-3 text-xs text-muted-foreground">
          Above the maximum touches limit — this step will not run.
        </p>
      )}
    </div>
  );
}

interface TemplateSelectProps {
  id: string;
  value: string | null;
  templates: MessageTemplate[];
  disabled: boolean;
  placeholder: string;
  onChange: (templateId: string | null) => void;
}

function TemplateSelect({
  id,
  value,
  templates,
  disabled,
  placeholder,
  onChange,
}: TemplateSelectProps) {
  return (
    <Select
      value={value ?? NONE_TEMPLATE}
      disabled={disabled}
      onValueChange={(next) => onChange(next === NONE_TEMPLATE ? null : next)}
    >
      <SelectTrigger id={id}>
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={NONE_TEMPLATE}>{placeholder}</SelectItem>
        {templates.map((template) => (
          <SelectItem key={template.id} value={template.id}>
            {template.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
