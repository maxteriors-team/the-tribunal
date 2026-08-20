"use client";

/**
 * Settings → Attach Rules: the cross-sell prompt (operator self-serve).
 *
 * The single biggest lever on average job value is the *second* service on a
 * quote: gutters on a roof, trim on siding. This screen is what turns "remember
 * to ask" into a rule the platform enforces at save time, per workspace, with no
 * code change.
 *
 * Each rule reads as a sentence — a `roof` job should also quote `gutters, trim`
 * — because that is how the operator thinks about it, and the enforcement dial
 * sits next to the sentence it governs. Mode always shows its consequence in
 * words: `Blocking` stops a rep saving a quote, which is the one genuinely
 * expensive decision on this page and must never be picked by accident.
 *
 * Suggested categories are offered from the workspace's own price book (the
 * distinct `service_category` values on its catalog items) rather than a fixed
 * list, so a business using its own trade names configures real rules. A rule
 * that names a category no longer in the price book keeps it and flags it,
 * because silently dropping it would silently stop the prompt.
 *
 * Saving PUTs the whole config back (the endpoint merges top-level keys and
 * replaces each provided one), so every field this editor exposes round-trips.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, Loader2, Plus, RotateCcw, Save, Trash2, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
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
import { Textarea } from "@/components/ui/textarea";
import { useSettingsSaveMutation } from "@/hooks/useSettingsSaveMutation";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { attachRulesApi } from "@/lib/api/attach-rules";
import { salesWizardApi } from "@/lib/api/sales-wizard";
import { queryKeys } from "@/lib/query-keys";
import type { AttachRule, AttachRuleMode, AttachRulesSettings } from "@/types/sales-wizard";

// The placeholder the backend interpolates (`app/schemas/attach_rules.py`).
const PROMPT_PLACEHOLDER = "{primary}";

interface ModeSpec {
  value: AttachRuleMode;
  label: string;
  /** What this mode actually does to a rep mid-quote. */
  consequence: string;
}

const MODES: readonly ModeSpec[] = [
  {
    value: "off",
    label: "Off",
    consequence: "Nothing is shown. The rule is kept for when you switch it back on.",
  },
  {
    value: "advisory",
    label: "Advisory",
    consequence:
      "The quote still saves. The rep sees the prompt and can add the service or dismiss it.",
  },
  {
    value: "blocking",
    label: "Blocking",
    consequence:
      "The quote will not save until the rep adds one of these services or gives a reason for skipping it.",
  },
];

/** Distinct, trimmed category names from the workspace price book, sorted. */
function priceBookCategories(items: readonly { service_category?: string | null }[]): string[] {
  const seen = new Map<string, string>();
  for (const item of items) {
    const name = (item.service_category ?? "").trim();
    if (!name) continue;
    const key = name.toLocaleLowerCase();
    if (!seen.has(key)) seen.set(key, name);
  }
  return [...seen.values()].sort((a, b) => a.localeCompare(b));
}

function sameCategory(a: string, b: string): boolean {
  return a.trim().toLocaleLowerCase() === b.trim().toLocaleLowerCase();
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function CategoryMultiSelect({
  id,
  labelId,
  selected,
  options,
  disabled,
  describedBy,
  onToggle,
}: {
  id: string;
  labelId: string;
  selected: string[];
  options: string[];
  disabled: boolean;
  describedBy: string;
  onToggle: (category: string) => void;
}) {
  // Options the rule already names but the price book no longer offers stay
  // listed (and flagged) so an edit elsewhere can never silently mute a rule.
  const unknown = selected.filter(
    (category) => !options.some((option) => sameCategory(option, category)),
  );
  const summary = selected.length === 0 ? "Choose services" : selected.join(", ");

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          id={id}
          type="button"
          variant="outline"
          disabled={disabled}
          aria-describedby={describedBy}
          // Name = the field label plus the current selection. A bare `for`
          // association alone would announce "Prompt to add, button" and drop
          // the chosen services, which are the only thing distinguishing one
          // rule's control from the next.
          aria-labelledby={`${labelId} ${id}-value`}
          className="w-full justify-between font-normal"
        >
          <span
            id={`${id}-value`}
            className={selected.length === 0 ? "truncate text-muted-foreground" : "truncate"}
          >
            {summary}
          </span>
          <ChevronDown className="ml-2 size-4 shrink-0 opacity-60" aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="max-h-72 w-64 overflow-y-auto">
        <DropdownMenuLabel>Services in your price book</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {options.length === 0 ? (
          <DropdownMenuLabel className="font-normal text-muted-foreground">
            No categorised price-book items yet.
          </DropdownMenuLabel>
        ) : (
          options.map((option) => (
            <DropdownMenuCheckboxItem
              key={option}
              checked={selected.some((category) => sameCategory(category, option))}
              // Keep the menu open: picking two or three add-ons is the norm.
              onSelect={(event) => event.preventDefault()}
              onCheckedChange={() => onToggle(option)}
            >
              {option}
            </DropdownMenuCheckboxItem>
          ))
        )}
        {unknown.length > 0 && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuLabel>Not in your price book</DropdownMenuLabel>
            {unknown.map((category) => (
              <DropdownMenuCheckboxItem
                key={category}
                checked
                onSelect={(event) => event.preventDefault()}
                onCheckedChange={() => onToggle(category)}
              >
                {category}
              </DropdownMenuCheckboxItem>
            ))}
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function RuleRow({
  index,
  rule,
  options,
  disabled,
  onChange,
  onRemove,
}: {
  index: number;
  rule: AttachRule;
  options: string[];
  disabled: boolean;
  onChange: (patch: Partial<AttachRule>) => void;
  onRemove: () => void;
}) {
  const primaryId = `attach-rule-${index}-primary`;
  const suggestedId = `attach-rule-${index}-suggested`;
  const modeId = `attach-rule-${index}-mode`;
  const consequenceId = `attach-rule-${index}-consequence`;
  const suggestedHintId = `attach-rule-${index}-suggested-hint`;

  const suggested = rule.suggested_categories ?? [];
  const mode = MODES.find((spec) => spec.value === rule.mode) ?? MODES[1];
  const primary = rule.primary_category.trim();

  const toggle = (category: string) =>
    onChange({
      suggested_categories: suggested.some((existing) => sameCategory(existing, category))
        ? suggested.filter((existing) => !sameCategory(existing, category))
        : [...suggested, category],
    });

  return (
    <li className="rounded-lg border bg-card p-4">
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm text-muted-foreground">
          A <span className="font-semibold text-foreground">{primary || "…"}</span> job should also
          quote{" "}
          <span className="font-semibold text-foreground">
            {suggested.length > 0 ? suggested.join(" or ") : "…"}
          </span>
          .
        </p>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          disabled={disabled}
          onClick={onRemove}
          aria-label={`Remove the ${primary || "untitled"} rule`}
        >
          <Trash2 className="size-4" />
        </Button>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <div className="space-y-2">
          <Label htmlFor={primaryId}>When the job is</Label>
          <Input
            id={primaryId}
            list="attach-rule-category-options"
            value={rule.primary_category}
            disabled={disabled}
            placeholder="roof"
            onChange={(event) => onChange({ primary_category: event.target.value })}
          />
        </div>

        <div className="space-y-2">
          <Label id={`${suggestedId}-label`} htmlFor={suggestedId}>
            Prompt to add
          </Label>
          <CategoryMultiSelect
            id={suggestedId}
            labelId={`${suggestedId}-label`}
            selected={suggested}
            options={options}
            disabled={disabled}
            describedBy={suggestedHintId}
            onToggle={toggle}
          />
          <p id={suggestedHintId} className="text-xs text-muted-foreground">
            Any one of these satisfies the rule.
          </p>
        </div>

        <div className="space-y-2">
          <Label htmlFor={modeId}>Enforcement</Label>
          <Select
            value={rule.mode}
            disabled={disabled}
            onValueChange={(value) => onChange({ mode: value as AttachRuleMode })}
          >
            <SelectTrigger id={modeId} aria-describedby={consequenceId}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {MODES.map((spec) => (
                <SelectItem key={spec.value} value={spec.value}>
                  {spec.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p id={consequenceId} className="text-xs text-muted-foreground">
            {mode.consequence}
          </p>
        </div>
      </div>

      {suggested.length === 0 && (
        <p className="mt-3 flex items-start gap-2 text-xs font-medium text-warning">
          <TriangleAlert className="mt-px size-3.5 shrink-0" aria-hidden />
          This rule prompts for nothing, so it will never fire.
        </p>
      )}
    </li>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function AttachRulesSettingsTab() {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();

  const { data, isPending } = useQuery({
    queryKey: queryKeys.attachRules.config(workspaceId ?? ""),
    queryFn: () => attachRulesApi.get(workspaceId!),
    enabled: !!workspaceId,
    // The editable draft seeds off this query's identity. Keep it stable so a
    // background refetch can never wipe an operator's unsaved edits.
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });

  // Category options come from the price book the rules actually match against.
  const catalogQuery = useQuery({
    queryKey: queryKeys.salesWizard.catalog(workspaceId ?? ""),
    queryFn: () => salesWizardApi.listCatalog(workspaceId!),
    enabled: !!workspaceId,
  });

  const [draft, setDraft] = useState<AttachRulesSettings | null>(null);
  const [server, setServer] = useState<AttachRulesSettings | null>(null);
  const [reasonInput, setReasonInput] = useState("");

  if (data && data !== server) {
    setServer(data);
    setDraft(data);
  }

  const mutation = useSettingsSaveMutation({
    mutationFn: (config: AttachRulesSettings) => attachRulesApi.update(workspaceId!, config),
    successMessage: "Attach rules are up to date.",
    errorMessage: "We couldn't save attach rules. Check your connection and try again.",
    onSuccess: (saved) => {
      queryClient.setQueryData(queryKeys.attachRules.config(workspaceId ?? ""), saved);
    },
  });

  if (isPending || !draft) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center py-12">
          <Loader2 className="size-6 animate-spin text-muted-foreground" />
          <span className="sr-only">Loading attach rules</span>
        </CardContent>
      </Card>
    );
  }

  const disabled = mutation.isPending;
  const options = priceBookCategories(catalogQuery.data ?? []);
  const rules = draft.rules ?? [];
  const reasons = draft.dismissal_reasons ?? [];

  const patch = (next: Partial<AttachRulesSettings>) =>
    setDraft((prev) => (prev ? { ...prev, ...next } : prev));

  const patchRule = (index: number, next: Partial<AttachRule>) =>
    patch({
      rules: rules.map((rule, i) => (i === index ? { ...rule, ...next } : rule)),
    });

  const addRule = () =>
    patch({
      rules: [...rules, { primary_category: "", suggested_categories: [], mode: "advisory" }],
    });

  const removeRule = (index: number) => patch({ rules: rules.filter((_, i) => i !== index) });

  const addReason = () => {
    const reason = reasonInput.trim();
    if (!reason) return;
    if (reasons.some((existing) => sameCategory(existing, reason))) {
      toast.error("That reason is already on the list");
      return;
    }
    patch({ dismissal_reasons: [...reasons, reason] });
    setReasonInput("");
  };

  const save = () => {
    const cleaned = rules
      .map((rule) => ({
        ...rule,
        primary_category: rule.primary_category.trim(),
        suggested_categories: (rule.suggested_categories ?? []).map((c) => c.trim()),
      }))
      .filter((rule) => rule.primary_category !== "");

    const template = draft.prompt_template.trim();
    if (!template) {
      toast.error("Give the prompt some wording");
      return;
    }
    if (draft.require_dismissal_reason && cleaned.length > 0 && reasons.length === 0) {
      toast.error("Add at least one dismissal reason, or stop requiring a reason");
      return;
    }

    mutation.mutate({
      ...draft,
      rules: cleaned,
      prompt_template: template,
      dismissal_reasons: reasons,
    });
  };

  const blockingCount = rules.filter((rule) => rule.mode === "blocking").length;
  const activeCount = rules.filter((rule) => rule.mode !== "off").length;

  return (
    <div className="space-y-6">
      {/* Shared option list so the primary-category input offers the same
          vocabulary as the multi-select without forcing a closed set. */}
      <datalist id="attach-rule-category-options">
        {options.map((option) => (
          // A datalist option is an autocomplete vocabulary entry, not a
          // labelable control — `value` is the whole content. Giving it text
          // children to satisfy the rule would make browsers render the
          // category twice in the dropdown ("Gutters — Gutters").
          // eslint-disable-next-line jsx-a11y/control-has-associated-label
          <option key={option} value={option} />
        ))}
      </datalist>

      <Card>
        <CardHeader>
          <div className="flex items-start justify-between gap-4">
            <div className="space-y-1.5">
              <CardTitle>Attach prompts</CardTitle>
              <CardDescription>
                Prompt the rep to quote a second service on every job. Gutters on a roof, trim on
                siding: the attach is what moves average job value, and it only happens if someone
                asks.
              </CardDescription>
            </div>
            <Switch
              checked={draft.enabled}
              onCheckedChange={(value) => patch({ enabled: value })}
              disabled={disabled}
              aria-label="Prompt for attachable services on quotes"
            />
          </div>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="space-y-2">
            <Label htmlFor="attach-prompt-template">Prompt wording</Label>
            <Textarea
              id="attach-prompt-template"
              rows={2}
              value={draft.prompt_template}
              disabled={disabled}
              aria-describedby="attach-prompt-template-hint"
              onChange={(event) => patch({ prompt_template: event.target.value })}
            />
            <p id="attach-prompt-template-hint" className="text-xs text-muted-foreground">
              What the rep reads when a service is missing.{" "}
              <code className="rounded bg-muted px-1 py-0.5">{PROMPT_PLACEHOLDER}</code> is replaced
              with the job type, for example &quot;roof&quot;.
            </p>
          </div>

          <div className="flex items-start justify-between gap-4 rounded-lg border bg-muted/20 p-4">
            <div className="space-y-1">
              <Label htmlFor="attach-require-reason" className="text-sm">
                Require a reason to skip
              </Label>
              <p className="text-sm text-muted-foreground">
                A dismissal without a reason is not reportable, so you can never tell a customer who
                declined from a rep who never asked.
              </p>
            </div>
            <Switch
              id="attach-require-reason"
              checked={draft.require_dismissal_reason}
              onCheckedChange={(value) => patch({ require_dismissal_reason: value })}
              disabled={disabled}
            />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Rules</CardTitle>
          <CardDescription>
            {rules.length === 0
              ? "No rules yet. Add one to start prompting."
              : `${activeCount} of ${rules.length} active${
                  blockingCount > 0 ? `, ${blockingCount} blocking a save until answered` : ""
                }.`}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {!draft.enabled && (
            <p className="flex items-start gap-2 rounded-lg border border-warning/40 bg-warning/5 p-3 text-sm text-warning">
              <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
              Attach prompts are switched off, so none of these rules run.
            </p>
          )}

          {rules.length > 0 && (
            <ul className="space-y-3">
              {rules.map((rule, index) => (
                <RuleRow
                  // Index-keyed on purpose: rules have no id, and the primary
                  // category is editable (so keying on it would remount the row
                  // on every keystroke and steal focus).
                  key={index}
                  index={index}
                  rule={rule}
                  options={options}
                  disabled={disabled}
                  onChange={(next) => patchRule(index, next)}
                  onRemove={() => removeRule(index)}
                />
              ))}
            </ul>
          )}

          <Button type="button" variant="outline" onClick={addRule} disabled={disabled}>
            <Plus className="size-4" /> Add a rule
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Reasons for skipping</CardTitle>
          <CardDescription>
            The vocabulary a rep picks from when they dismiss a prompt. These are what turn a low
            attach rate into a diagnosis.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {reasons.length > 0 && (
            <ul className="flex flex-wrap gap-2">
              {reasons.map((reason) => (
                <li key={reason}>
                  <Badge variant="secondary" className="gap-1.5 py-1 pl-2.5 pr-1">
                    {reason}
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      disabled={disabled}
                      aria-label={`Remove reason ${reason}`}
                      className="size-5"
                      onClick={() =>
                        patch({
                          dismissal_reasons: reasons.filter((r) => r !== reason),
                        })
                      }
                    >
                      <Trash2 className="size-3" />
                    </Button>
                  </Badge>
                </li>
              ))}
            </ul>
          )}

          <div className="flex flex-wrap items-end gap-3">
            <div className="min-w-56 flex-1 space-y-2">
              <Label htmlFor="attach-new-reason">Add a reason</Label>
              <Input
                id="attach-new-reason"
                value={reasonInput}
                disabled={disabled}
                placeholder="Customer declined"
                onChange={(event) => setReasonInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    addReason();
                  }
                }}
              />
            </div>
            <Button
              type="button"
              variant="outline"
              onClick={addReason}
              disabled={disabled || reasonInput.trim() === ""}
            >
              <Plus className="size-4" /> Add
            </Button>
          </div>
        </CardContent>
      </Card>

      <Separator />

      <div className="flex flex-wrap items-center justify-end gap-3">
        <Button
          type="button"
          variant="outline"
          disabled={disabled || !server}
          onClick={() => {
            if (server) setDraft(server);
            setReasonInput("");
          }}
        >
          <RotateCcw className="size-4" /> Discard changes
        </Button>
        <Button type="button" onClick={save} disabled={disabled}>
          {mutation.isPending ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <Save className="size-4" />
          )}
          Save attach rules
        </Button>
      </div>
    </div>
  );
}
