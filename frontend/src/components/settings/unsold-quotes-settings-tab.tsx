"use client";

/**
 * Settings → Unsold Quotes: the quiet-quote sequence (operator self-serve).
 *
 * Every quote sitting in `sent` or `expired` is a job that was measured, priced
 * and agreed, then dropped. This screen is what turns "someone should chase
 * those" into a cadence the platform runs: which days after the quote goes out,
 * what each touch leads with, and which message a $12,000 project gets versus a
 * $1,500 one.
 *
 * The screen is built around the fact that turning it on **texts real past
 * customers**. So every control states its consequence in words, the sequence
 * is summarised as a sentence before it is saved, touches beyond the stop-after
 * limit are shown as explicitly not sending rather than quietly ignored, and
 * quiet hours sit on the same page rather than in a different tab.
 *
 * Copy lives in the workspace's Message Templates library, referenced by name,
 * so the wording is written and edited where every other saved message is. A
 * touch with no template named falls back to the built-in copy for its hook
 * rather than sending nothing.
 *
 * Saving PUTs the whole config back (the endpoint merges top-level keys and
 * replaces each provided one), so every field this editor exposes round-trips.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Clock, Loader2, Plus, RotateCcw, Save, Trash2, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { cid } from "@/components/settings/editor-keys";
import { Badge } from "@/components/ui/badge";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { messageTemplatesApi } from "@/lib/api/message-templates";
import {
  unsoldQuotesApi,
  type UnsoldQuoteHook,
  type UnsoldQuoteSettings,
  type UnsoldQuoteSettingsUpdate,
} from "@/lib/api/unsold-quotes";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { formatWholeCurrency } from "@/lib/utils/number";

// Mirrors `MAX_TOUCHES` / `MAX_DAY_OFFSET` in `app/schemas/unsold_quotes.py`.
const MAX_TOUCHES = 6;
const MAX_DAY_OFFSET = 730;

/** Sentinel for "no template named" — Radix Select reserves the empty string. */
const BUILT_IN = "__built_in__";

interface HookSpec {
  value: UnsoldQuoteHook;
  label: string;
  /** Why this touch is reaching out, in the operator's words. */
  reason: string;
}

const HOOKS: readonly HookSpec[] = [
  {
    value: "price_validity",
    label: "Price validity",
    reason: "The number on the estimate will not hold forever.",
  },
  {
    value: "seasonal",
    label: "Seasonal slots",
    reason: "The calendar is filling and the work is weather-bound.",
  },
  {
    value: "financing",
    label: "Financing",
    reason: "The total, not the job, was the objection.",
  },
];

function hookSpec(hook: UnsoldQuoteHook): HookSpec {
  return HOOKS.find((spec) => spec.value === hook) ?? HOOKS[0];
}

// ---------------------------------------------------------------------------
// Draft model
//
// Numbers are held as strings so a half-typed "3" in a day box stays exactly
// what the operator typed. Parsing happens at validation and save.
// ---------------------------------------------------------------------------

export interface TouchDraft {
  /** Client-only list key; never sent. */
  key: string;
  dayOffset: string;
  hook: UnsoldQuoteHook;
  /** `null` means "use the built-in copy for this hook". */
  templateName: string | null;
  highValueTemplateName: string | null;
}

export interface SequenceDraft {
  enabled: boolean;
  touches: TouchDraft[];
  maxTouches: string;
  valueThreshold: string;
  quietStart: string;
  quietEnd: string;
  timezone: string;
}

export function toDraft(settings: UnsoldQuoteSettings): SequenceDraft {
  return {
    enabled: settings.enabled,
    touches: (settings.touches ?? []).map((touch) => ({
      key: cid(),
      dayOffset: String(touch.day_offset),
      hook: touch.hook,
      templateName: touch.template_name ?? null,
      highValueTemplateName: touch.high_value_template_name ?? null,
    })),
    maxTouches: String(settings.max_touches),
    valueThreshold: String(settings.value_threshold),
    quietStart: settings.quiet_hours_start ?? "",
    quietEnd: settings.quiet_hours_end ?? "",
    timezone: settings.timezone ?? "",
  };
}

export function toPayload(draft: SequenceDraft): UnsoldQuoteSettingsUpdate {
  return {
    enabled: draft.enabled,
    touches: draft.touches.map((touch) => ({
      day_offset: Number(touch.dayOffset),
      hook: touch.hook,
      template_name: touch.templateName,
      high_value_template_name: touch.highValueTemplateName,
    })),
    max_touches: Number(draft.maxTouches),
    value_threshold: Number(draft.valueThreshold),
    quiet_hours_start: draft.quietStart.trim() || null,
    quiet_hours_end: draft.quietEnd.trim() || null,
    timezone: draft.timezone.trim() || null,
  };
}

export interface SequenceErrors {
  /** Keyed by touch row key. */
  touches: Record<string, string>;
  maxTouches?: string;
  valueThreshold?: string;
  quietHours?: string;
}

export function hasErrors(errors: SequenceErrors): boolean {
  return (
    Object.keys(errors.touches).length > 0 ||
    errors.maxTouches !== undefined ||
    errors.valueThreshold !== undefined ||
    errors.quietHours !== undefined
  );
}

/**
 * Validate a draft. An empty result means it is safe to save.
 *
 * Duplicate days are an error here rather than a silent clean-up: the backend
 * de-duplicates on write, so a config that looks like four touches would come
 * back as three and the operator would never be told which one was dropped.
 */
export function validateDraft(draft: SequenceDraft): SequenceErrors {
  const errors: SequenceErrors = { touches: {} };
  const seenDays = new Map<number, string>();

  for (const touch of draft.touches) {
    const day = Number(touch.dayOffset.trim());
    if (touch.dayOffset.trim() === "" || !Number.isFinite(day) || !Number.isInteger(day)) {
      errors.touches[touch.key] = "Enter a whole number of days.";
      continue;
    }
    if (day < 1 || day > MAX_DAY_OFFSET) {
      errors.touches[touch.key] = `Days must be between 1 and ${MAX_DAY_OFFSET}.`;
      continue;
    }
    const clash = seenDays.get(day);
    if (clash !== undefined) {
      errors.touches[touch.key] = "Another touch already uses this day.";
      continue;
    }
    seenDays.set(day, touch.key);
  }

  const stopAfter = Number(draft.maxTouches.trim());
  if (
    draft.maxTouches.trim() === "" ||
    !Number.isInteger(stopAfter) ||
    stopAfter < 0 ||
    stopAfter > MAX_TOUCHES
  ) {
    errors.maxTouches = `Stop after must be between 0 and ${MAX_TOUCHES}.`;
  }

  const threshold = Number(draft.valueThreshold.trim());
  if (draft.valueThreshold.trim() === "" || !Number.isFinite(threshold) || threshold < 0) {
    errors.valueThreshold = "Enter an amount of $0 or more.";
  }

  const start = draft.quietStart.trim();
  const end = draft.quietEnd.trim();
  if ((start === "") !== (end === "")) {
    errors.quietHours = "Set both a start and an end, or clear both.";
  }

  return errors;
}

/** The touches that will actually send, in cadence order. */
export function activeTouches(draft: SequenceDraft): TouchDraft[] {
  const stopAfter = Number(draft.maxTouches.trim());
  const limit = Number.isInteger(stopAfter) && stopAfter >= 0 ? stopAfter : draft.touches.length;
  return [...draft.touches]
    .sort((a, b) => Number(a.dayOffset) - Number(b.dayOffset))
    .slice(0, limit);
}

/**
 * One sentence stating exactly what saving this draft will do.
 *
 * This is the safety rail on the page: it is the only place that reads back
 * *sending* behaviour (how many texts, on which days, in whose evening they are
 * suppressed) rather than the individual settings that imply it.
 */
export function describeSequence(draft: SequenceDraft): string {
  if (!draft.enabled) {
    return "Follow-up is off. No messages are sent, and the cadence below is kept for when you switch it on.";
  }

  const active = activeTouches(draft);
  if (active.length === 0) {
    return "No touches will send: add one, or raise the stop-after limit.";
  }

  const days = active.map((touch) => `day ${touch.dayOffset}`).join(", ");
  const noun = active.length === 1 ? "message" : "messages";
  const quiet =
    draft.quietStart.trim() && draft.quietEnd.trim()
      ? ` Nothing sends between ${draft.quietStart.trim()} and ${draft.quietEnd.trim()}${
          draft.timezone.trim() ? ` (${draft.timezone.trim()})` : ""
        }.`
      : " Quiet hours are off, so a touch can send at any hour.";

  return `Each unsold quote gets ${active.length} ${noun}: ${days} after it was issued.${quiet}`;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function TemplateSelect({
  id,
  label,
  hint,
  value,
  options,
  disabled,
  onChange,
}: {
  id: string;
  label: string;
  hint: string;
  value: string | null;
  options: string[];
  disabled: boolean;
  onChange: (value: string | null) => void;
}) {
  // A template that has since been deleted stays listed, because dropping it
  // would silently swap the operator's copy for the built-in text.
  const missing = value !== null && !options.includes(value);

  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{label}</Label>
      <Select
        value={value ?? BUILT_IN}
        disabled={disabled}
        onValueChange={(next) => onChange(next === BUILT_IN ? null : next)}
      >
        <SelectTrigger id={id} aria-describedby={`${id}-hint`}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={BUILT_IN}>Built-in message</SelectItem>
          {options.map((name) => (
            <SelectItem key={name} value={name}>
              {name}
            </SelectItem>
          ))}
          {missing && value !== null && (
            <SelectItem value={value}>{value} (not in your library)</SelectItem>
          )}
        </SelectContent>
      </Select>
      <p id={`${id}-hint`} className="text-xs text-muted-foreground">
        {missing ? "This template is no longer in your library." : hint}
      </p>
    </div>
  );
}

function TouchRow({
  index,
  touch,
  templates,
  threshold,
  willSend,
  error,
  disabled,
  onChange,
  onRemove,
}: {
  index: number;
  touch: TouchDraft;
  templates: string[];
  threshold: number | null;
  willSend: boolean;
  error: string | undefined;
  disabled: boolean;
  onChange: (patch: Partial<TouchDraft>) => void;
  onRemove: () => void;
}) {
  const dayId = `unsold-touch-${index}-day`;
  const hookId = `unsold-touch-${index}-hook`;
  const standardId = `unsold-touch-${index}-standard`;
  const highValueId = `unsold-touch-${index}-high-value`;
  const spec = hookSpec(touch.hook);
  const thresholdLabel = threshold === null ? "the threshold" : formatWholeCurrency(threshold);

  return (
    <li className={willSend ? "rounded-lg border bg-card p-4" : "rounded-lg border bg-muted/40 p-4"}>
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm text-muted-foreground">
          <span className="font-semibold text-foreground">
            Day {touch.dayOffset.trim() || "…"}
          </span>{" "}
          after the quote was issued, lead with{" "}
          <span className="font-semibold text-foreground">{spec.label.toLowerCase()}</span>.
        </p>
        <div className="flex shrink-0 items-center gap-2">
          {!willSend && <Badge variant="secondary">Not sent</Badge>}
          <Button
            type="button"
            variant="ghost"
            size="icon"
            disabled={disabled}
            onClick={onRemove}
            aria-label={`Remove the day ${touch.dayOffset || "untitled"} touch`}
          >
            <Trash2 className="size-4" />
          </Button>
        </div>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-4">
        <div className="space-y-2">
          <Label htmlFor={dayId}>Days after issue</Label>
          <Input
            id={dayId}
            type="number"
            inputMode="numeric"
            min={1}
            max={MAX_DAY_OFFSET}
            step="1"
            value={touch.dayOffset}
            disabled={disabled}
            aria-invalid={error !== undefined}
            aria-describedby={`${dayId}-hint`}
            onChange={(event) => onChange({ dayOffset: event.target.value })}
          />
          <p
            id={`${dayId}-hint`}
            className={
              error === undefined
                ? "text-xs text-muted-foreground"
                : "text-xs font-medium text-destructive"
            }
          >
            {error ?? "Counted from the quote's issue date."}
          </p>
        </div>

        <div className="space-y-2">
          <Label htmlFor={hookId}>Lead with</Label>
          <Select
            value={touch.hook}
            disabled={disabled}
            onValueChange={(value) => onChange({ hook: value as UnsoldQuoteHook })}
          >
            <SelectTrigger id={hookId} aria-describedby={`${hookId}-hint`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {HOOKS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p id={`${hookId}-hint`} className="text-xs text-muted-foreground">
            {spec.reason}
          </p>
        </div>

        <TemplateSelect
          id={standardId}
          label={`Under ${thresholdLabel}`}
          hint="Message used for smaller jobs."
          value={touch.templateName}
          options={templates}
          disabled={disabled}
          onChange={(value) => onChange({ templateName: value })}
        />

        <TemplateSelect
          id={highValueId}
          label={`${thresholdLabel} and up`}
          hint="Message used for large projects."
          value={touch.highValueTemplateName}
          options={templates}
          disabled={disabled}
          onChange={(value) => onChange({ highValueTemplateName: value })}
        />
      </div>
    </li>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function UnsoldQuotesSettingsTab() {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();

  const { data, isPending } = useQuery({
    queryKey: queryKeys.settings.unsoldQuotes(workspaceId ?? ""),
    queryFn: () => unsoldQuotesApi.get(workspaceId!),
    enabled: !!workspaceId,
    // The editable draft seeds off this query's identity. Keep it stable so a
    // background refetch can never wipe an operator's unsaved edits.
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });

  const templatesQuery = useQuery({
    queryKey: queryKeys.messageTemplates.all(workspaceId ?? ""),
    queryFn: () => messageTemplatesApi.list(workspaceId!),
    enabled: !!workspaceId,
  });

  const [draft, setDraft] = useState<SequenceDraft | null>(null);
  const [server, setServer] = useState<UnsoldQuoteSettings | null>(null);

  if (data && data !== server) {
    setServer(data);
    setDraft(toDraft(data));
  }

  const mutation = useMutation({
    mutationFn: (payload: UnsoldQuoteSettingsUpdate) =>
      unsoldQuotesApi.update(workspaceId!, payload),
    onSuccess: (saved) => {
      queryClient.setQueryData(queryKeys.settings.unsoldQuotes(workspaceId ?? ""), saved);
      toast.success("Unsold quote follow-up saved");
    },
    onError: (error: unknown) =>
      toast.error(getApiErrorMessage(error, "Failed to save unsold quote follow-up")),
  });

  if (isPending || !draft) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center py-12">
          <Loader2 className="size-6 animate-spin text-muted-foreground" />
          <span className="sr-only">Loading unsold quote settings</span>
        </CardContent>
      </Card>
    );
  }

  const disabled = mutation.isPending;
  const templates = (templatesQuery.data?.items ?? []).map((template) => template.name);
  const errors = validateDraft(draft);
  const blocked = hasErrors(errors);
  const parsedThreshold = Number(draft.valueThreshold.trim());
  const threshold =
    draft.valueThreshold.trim() !== "" && Number.isFinite(parsedThreshold)
      ? parsedThreshold
      : null;
  const sending = new Set(activeTouches(draft).map((touch) => touch.key));

  const patch = (next: Partial<SequenceDraft>) =>
    setDraft((prev) => (prev ? { ...prev, ...next } : prev));

  const patchTouch = (key: string, next: Partial<TouchDraft>) =>
    patch({
      touches: draft.touches.map((touch) =>
        touch.key === key ? { ...touch, ...next } : touch,
      ),
    });

  const addTouch = () => {
    if (draft.touches.length >= MAX_TOUCHES) {
      toast.error(`A sequence tops out at ${MAX_TOUCHES} touches.`);
      return;
    }
    const lastDay = draft.touches.reduce(
      (max, touch) => Math.max(max, Number(touch.dayOffset) || 0),
      0,
    );
    patch({
      touches: [
        ...draft.touches,
        {
          key: cid(),
          dayOffset: String(Math.min(lastDay + 30, MAX_DAY_OFFSET)),
          hook: "price_validity",
          templateName: null,
          highValueTemplateName: null,
        },
      ],
    });
  };

  const save = () => {
    if (blocked) return;
    mutation.mutate(toPayload(draft));
  };

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <div className="flex items-start justify-between gap-4">
            <div className="space-y-1.5">
              <CardTitle>Unsold quote follow-up</CardTitle>
              <CardDescription>
                Work the quotes that were sent and went quiet. The site visit is
                already paid for and the price is already agreed, so these are the
                warmest leads you own. Turning this on texts past customers.
              </CardDescription>
            </div>
            <Switch
              checked={draft.enabled}
              onCheckedChange={(value) => patch({ enabled: value })}
              disabled={disabled}
              aria-label="Follow up on unsold quotes"
            />
          </div>
        </CardHeader>
        <CardContent>
          <p
            role="status"
            aria-live="polite"
            className="rounded-lg border bg-muted/30 p-4 text-sm text-foreground"
          >
            {describeSequence(draft)}
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Sequence</CardTitle>
          <CardDescription>
            Only quotes still sitting in Sent or Expired are worked. A quote that
            was approved or declined is never chased, and each quote stops after
            its final touch.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {draft.touches.length > 0 && (
            <ul className="space-y-3">
              {draft.touches.map((touch, index) => (
                <TouchRow
                  key={touch.key}
                  index={index}
                  touch={touch}
                  templates={templates}
                  threshold={threshold}
                  willSend={sending.has(touch.key)}
                  error={errors.touches[touch.key]}
                  disabled={disabled}
                  onChange={(next) => patchTouch(touch.key, next)}
                  onRemove={() =>
                    patch({ touches: draft.touches.filter((row) => row.key !== touch.key) })
                  }
                />
              ))}
            </ul>
          )}

          <div className="flex flex-wrap items-end justify-between gap-4">
            <Button
              type="button"
              variant="outline"
              onClick={addTouch}
              disabled={disabled || draft.touches.length >= MAX_TOUCHES}
            >
              <Plus className="size-4" /> Add a touch
            </Button>

            <div className="w-40 space-y-2">
              <Label htmlFor="unsold-max-touches">Stop after</Label>
              <Input
                id="unsold-max-touches"
                type="number"
                inputMode="numeric"
                min={0}
                max={MAX_TOUCHES}
                step="1"
                value={draft.maxTouches}
                disabled={disabled}
                aria-invalid={errors.maxTouches !== undefined}
                aria-describedby="unsold-max-touches-hint"
                onChange={(event) => patch({ maxTouches: event.target.value })}
              />
              <p
                id="unsold-max-touches-hint"
                className={
                  errors.maxTouches === undefined
                    ? "text-xs text-muted-foreground"
                    : "text-xs font-medium text-destructive"
                }
              >
                {errors.maxTouches ?? "Touches beyond this are kept, not sent."}
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Job size</CardTitle>
          <CardDescription>
            A large project and a small job are not the same conversation, so
            each touch carries two messages and the quote total picks between
            them.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="max-w-sm space-y-2">
            <Label htmlFor="unsold-value-threshold">Large job starts at ($)</Label>
            <Input
              id="unsold-value-threshold"
              type="number"
              inputMode="decimal"
              min={0}
              step="500"
              value={draft.valueThreshold}
              disabled={disabled}
              aria-invalid={errors.valueThreshold !== undefined}
              aria-describedby="unsold-value-threshold-hint"
              onChange={(event) => patch({ valueThreshold: event.target.value })}
            />
            <p
              id="unsold-value-threshold-hint"
              className={
                errors.valueThreshold === undefined
                  ? "text-xs text-muted-foreground"
                  : "text-xs font-medium text-destructive"
              }
            >
              {errors.valueThreshold ??
                "Quotes at or above this total get the large-job message."}
            </p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Clock className="size-5" aria-hidden /> Quiet hours
          </CardTitle>
          <CardDescription>
            An unsold-quote nudge is never urgent. Sends are held during these
            local hours; leave both blank to send at any hour.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid max-w-2xl gap-4 sm:grid-cols-3">
            <div className="space-y-2">
              <Label htmlFor="unsold-quiet-start">Start</Label>
              <Input
                id="unsold-quiet-start"
                type="time"
                value={draft.quietStart}
                disabled={disabled}
                aria-invalid={errors.quietHours !== undefined}
                onChange={(event) => patch({ quietStart: event.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="unsold-quiet-end">End</Label>
              <Input
                id="unsold-quiet-end"
                type="time"
                value={draft.quietEnd}
                disabled={disabled}
                aria-invalid={errors.quietHours !== undefined}
                onChange={(event) => patch({ quietEnd: event.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="unsold-quiet-timezone">Timezone</Label>
              <Input
                id="unsold-quiet-timezone"
                value={draft.timezone}
                disabled={disabled}
                placeholder="America/Detroit"
                aria-describedby="unsold-quiet-timezone-hint"
                onChange={(event) => patch({ timezone: event.target.value })}
              />
              <p id="unsold-quiet-timezone-hint" className="text-xs text-muted-foreground">
                Defaults to your workspace timezone.
              </p>
            </div>
          </div>

          {errors.quietHours !== undefined && (
            <p className="flex items-start gap-2 text-sm font-medium text-destructive">
              <TriangleAlert className="mt-px size-4 shrink-0" aria-hidden />
              {errors.quietHours}
            </p>
          )}
        </CardContent>
      </Card>

      <Separator />

      <div className="flex flex-wrap items-center justify-end gap-3">
        <Button
          type="button"
          variant="outline"
          disabled={disabled || !server}
          onClick={() => {
            if (server) setDraft(toDraft(server));
          }}
        >
          <RotateCcw className="size-4" /> Discard changes
        </Button>
        <Button type="button" onClick={save} disabled={disabled || blocked}>
          {mutation.isPending ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <Save className="size-4" />
          )}
          Save follow-up
        </Button>
      </div>
    </div>
  );
}
