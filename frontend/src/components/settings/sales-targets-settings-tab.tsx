"use client";

/**
 * Settings → Sales Targets: the monthly revenue plan (operator self-serve).
 *
 * A metro Detroit exteriors business does not sell the same number twice: June
 * is gutters and roof washing, December is holiday lighting, February is close
 * to nothing. A single flat "monthly goal" would be wrong eleven months a year,
 * so this editor is built around a **default month plan** plus **per-month
 * overrides** for one calendar year at a time.
 *
 * Storage note. `revenue_targets` holds one row per calendar month and has no
 * "default" column, so the default here is a planning affordance over real
 * rows, not a second kind of record:
 *
 * - **Save** bulk-upserts a row for every writable month of the selected year,
 *   using that month's override when it has one and the default plan otherwise.
 *   Real rows are what `/revenue-targets/pace` reads, so this is what makes the
 *   dashboard pace widget work for every planned month.
 * - **Load** re-derives the default as the plan shared by the most writable
 *   months of the year; months that differ are flagged Custom. That round-trips
 *   a saved year exactly.
 *
 * History is protected. Save writes only months from the current month onward,
 * plus any past month the operator deliberately edited in this session. Last
 * June's goal has to stay readable after this June's is set, so the editor
 * never silently rewrites a month that has already happened.
 *
 * The live backsolve is the point of the screen. Typing a goal immediately
 * reports the jobs, estimates and leads it implies, which is what makes an
 * unrealistic number obvious before it is committed rather than in October.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarRange, Loader2, RotateCcw, Save, Target } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

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
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import {
  revenueTargetsApi,
  type RevenueTarget,
  type RevenueTargetList,
  type RevenueTargetPlan,
  type RevenueTargetUpsert,
} from "@/lib/api/revenue-targets";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { formatNumber, formatWholeCurrency } from "@/lib/utils/number";

// ---------------------------------------------------------------------------
// Backsolve maths (pure)
//
// Mirrors `app.services.reporting.revenue_target_service.backsolve_funnel` so
// the number the operator types against here is the number the dashboard
// measures them against later:
//
//     jobs      = revenue_goal / target_avg_job_value
//     estimates = jobs / (target_close_rate / 100)
//     leads     = estimates / (assumed_sat_rate / 100)
//
// Every divisor is optional or operator-supplied, so a missing *or*
// non-positive value is "unknown": that stage and everything downstream of it
// report null. A workspace that never entered an average job value gets "we
// don't know", never a zero it might mistake for a real requirement.
// ---------------------------------------------------------------------------

export interface BacksolveInput {
  revenueGoal: number | null;
  avgJobValue: number | null;
  /** Percent (0..100] of sat estimates that close. */
  closeRatePct: number | null;
  /** Percent (0..100] of leads that become a sat (run) estimate. */
  satRatePct: number | null;
  /** The operator's own lead number; overrides the derived one when set. */
  targetLeads: number | null;
}

export interface FunnelBacksolve {
  jobs: number | null;
  estimates: number | null;
  leads: number | null;
}

/** Return `value` only when it is safe to divide by. */
function divisor(value: number | null): number | null {
  if (value === null || !Number.isFinite(value) || value <= 0) return null;
  return value;
}

/**
 * Turn a revenue goal into the whole-month stage counts required to hit it.
 *
 * Values are raw (unrounded) on purpose. Rounding each stage before feeding the
 * next would compound: ceiling 55.56 estimates to 56 before dividing by the sat
 * rate reports 94 leads where the honest answer is 93. Round only for display.
 */
export function backsolveFunnel(input: BacksolveInput): FunnelBacksolve {
  const goal = input.revenueGoal;
  const avgJobValue = divisor(input.avgJobValue);
  const jobs =
    goal !== null && Number.isFinite(goal) && avgJobValue !== null
      ? goal / avgJobValue
      : null;

  const closeRate = divisor(input.closeRatePct);
  const estimates = jobs !== null && closeRate !== null ? jobs / (closeRate / 100) : null;

  const satRate = divisor(input.satRatePct);
  const derivedLeads =
    estimates !== null && satRate !== null ? estimates / (satRate / 100) : null;
  // A hand-set lead target beats a derived one, exactly as the backend does.
  const leads =
    input.targetLeads !== null && Number.isFinite(input.targetLeads)
      ? input.targetLeads
      : derivedLeads;

  return { jobs, estimates, leads };
}

/** Round a required count up: you cannot run 0.56 of an estimate. */
function requiredCount(value: number | null): number | null {
  return value === null ? null : Math.ceil(value);
}

function percentLabel(value: number): string {
  return `${formatNumber(value)}%`;
}

export interface BacksolveReadout {
  /** What the entered assumptions already prove, always led by the goal. */
  sentence: string;
  /** The next assumption worth adding, or null when the chain is complete. */
  missing: string | null;
}

/**
 * Describe a goal as the funnel it demands, e.g.
 * "$100,000 at $5,000 avg job = 20 jobs, at 36% close = 56 estimates,
 * at 60% sat rate = 93 leads/month."
 *
 * The chain truncates at the first missing assumption and says which one it is,
 * so the read-out never implies a requirement the operator never expressed.
 */
export function describeBacksolve(input: BacksolveInput): BacksolveReadout {
  const goal = input.revenueGoal;
  if (goal === null || !Number.isFinite(goal) || goal <= 0) {
    return {
      sentence: "",
      missing: "Enter a monthly revenue goal to see what it takes to hit it.",
    };
  }

  const funnel = backsolveFunnel(input);
  const goalLabel = formatWholeCurrency(goal);

  if (funnel.jobs === null || input.avgJobValue === null) {
    return {
      sentence: `${goalLabel}/month.`,
      missing:
        "Add a target average job value to see the jobs, estimates and leads this goal needs.",
    };
  }

  const clauses = [
    `${goalLabel} at ${formatWholeCurrency(input.avgJobValue)} avg job = ${formatNumber(
      requiredCount(funnel.jobs) as number,
    )} jobs`,
  ];

  if (funnel.estimates === null || input.closeRatePct === null) {
    // A hand-set lead target still stands on its own without a close rate.
    if (input.targetLeads !== null && Number.isFinite(input.targetLeads)) {
      clauses.push(`${formatNumber(input.targetLeads)} leads/month (your target)`);
      return { sentence: `${clauses.join(", ")}.`, missing: null };
    }
    return {
      sentence: `${clauses.join(", ")}.`,
      missing: "Add a close rate to see the estimates and leads this goal needs.",
    };
  }

  clauses.push(
    `at ${percentLabel(input.closeRatePct)} close = ${formatNumber(
      requiredCount(funnel.estimates) as number,
    )} estimates`,
  );

  if (input.targetLeads !== null && Number.isFinite(input.targetLeads)) {
    clauses.push(`${formatNumber(input.targetLeads)} leads/month (your target)`);
    return { sentence: `${clauses.join(", ")}.`, missing: null };
  }

  if (funnel.leads === null || input.satRatePct === null) {
    return {
      sentence: `${clauses.join(", ")}.`,
      missing: "Add a sat rate to see the leads this goal needs.",
    };
  }

  clauses.push(
    `at ${percentLabel(input.satRatePct)} sat rate = ${formatNumber(
      requiredCount(funnel.leads) as number,
    )} leads/month`,
  );
  return { sentence: `${clauses.join(", ")}.`, missing: null };
}

// ---------------------------------------------------------------------------
// Draft model
//
// Fields are held as strings so a half-typed "1" in a number box stays exactly
// what the operator typed. Parsing happens at validation and save.
// ---------------------------------------------------------------------------

export interface PlanDraft {
  revenueGoal: string;
  avgJobValue: string;
  closeRate: string;
  satRate: string;
  targetLeads: string;
  estimateCapacity: string;
  crewHours: string;
  backlogWeeks: string;
}

type PlanField = keyof PlanDraft;
type PlanErrors = Partial<Record<PlanField, string>>;

/** Industry-typical share of leads that turn into a sat (run) estimate. */
const DEFAULT_SAT_RATE = "60";

const EMPTY_PLAN: PlanDraft = {
  revenueGoal: "",
  avgJobValue: "",
  closeRate: "",
  satRate: DEFAULT_SAT_RATE,
  targetLeads: "",
  estimateCapacity: "",
  crewHours: "",
  backlogWeeks: "",
};

interface FieldSpec {
  key: PlanField;
  label: string;
  hint: string;
  step: string;
  min: number;
  max?: number;
}

const PLAN_FIELDS: readonly FieldSpec[] = [
  {
    key: "revenueGoal",
    label: "Monthly revenue goal ($)",
    hint: "What you intend to sell in the month.",
    step: "1000",
    min: 0,
  },
  {
    key: "avgJobValue",
    label: "Target average job value ($)",
    hint: "Mean ticket the goal assumes.",
    step: "100",
    min: 0,
  },
  {
    key: "closeRate",
    label: "Target close rate (%)",
    hint: "Share of run estimates that close.",
    step: "1",
    min: 1,
    max: 100,
  },
  {
    key: "satRate",
    label: "Assumed sat rate (%)",
    hint: "Share of leads that turn into a run estimate.",
    step: "1",
    min: 1,
    max: 100,
  },
  {
    key: "targetLeads",
    label: "Target leads / month",
    hint: "Optional. Overrides the backsolved lead number.",
    step: "1",
    min: 0,
  },
  {
    key: "estimateCapacity",
    label: "Estimate capacity / month",
    hint: "Estimates you can actually run.",
    step: "1",
    min: 0,
  },
  {
    key: "crewHours",
    label: "Crew capacity (hours / week)",
    hint: "Sellable crew hours available.",
    step: "1",
    min: 0,
  },
  {
    key: "backlogWeeks",
    label: "Backlog alert (weeks)",
    hint: "Booked-out length that should raise a flag.",
    step: "0.5",
    min: 0,
  },
];

function parseOptional(value: string): number | null {
  const trimmed = value.trim();
  if (trimmed === "") return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : Number.NaN;
}

function toNumberOrNull(value: string): number | null {
  const parsed = parseOptional(value);
  return parsed === null || Number.isNaN(parsed) ? null : parsed;
}

/** Validate one plan. An empty result means the plan is safe to save. */
export function validatePlan(draft: PlanDraft): PlanErrors {
  const errors: PlanErrors = {};

  const goal = parseOptional(draft.revenueGoal);
  if (goal === null || Number.isNaN(goal) || goal <= 0) {
    errors.revenueGoal = "Enter a revenue goal above $0.";
  }

  const avgJobValue = parseOptional(draft.avgJobValue);
  if (avgJobValue !== null && (Number.isNaN(avgJobValue) || avgJobValue <= 0)) {
    errors.avgJobValue = "Average job value must be more than $0.";
  }

  const closeRate = parseOptional(draft.closeRate);
  if (
    closeRate !== null &&
    (Number.isNaN(closeRate) || closeRate < 1 || closeRate > 100)
  ) {
    errors.closeRate = "Close rate must be between 1 and 100.";
  }

  const satRate = parseOptional(draft.satRate);
  if (satRate === null || Number.isNaN(satRate) || satRate < 1 || satRate > 100) {
    errors.satRate = "Sat rate must be between 1 and 100.";
  }

  for (const key of ["targetLeads", "estimateCapacity", "crewHours", "backlogWeeks"] as const) {
    const value = parseOptional(draft[key]);
    if (value !== null && (Number.isNaN(value) || value < 0)) {
      errors[key] = "Must be zero or more.";
    }
  }

  return errors;
}

function draftToInput(draft: PlanDraft): BacksolveInput {
  return {
    revenueGoal: toNumberOrNull(draft.revenueGoal),
    avgJobValue: toNumberOrNull(draft.avgJobValue),
    closeRatePct: toNumberOrNull(draft.closeRate),
    satRatePct: toNumberOrNull(draft.satRate),
    targetLeads: toNumberOrNull(draft.targetLeads),
  };
}

function draftToPlan(draft: PlanDraft): RevenueTargetPlan {
  return {
    revenue_goal: toNumberOrNull(draft.revenueGoal) ?? 0,
    target_avg_job_value: toNumberOrNull(draft.avgJobValue),
    target_close_rate: toNumberOrNull(draft.closeRate),
    assumed_sat_rate: toNumberOrNull(draft.satRate) ?? Number(DEFAULT_SAT_RATE),
    target_leads: toNumberOrNull(draft.targetLeads),
    estimate_capacity_per_month: toNumberOrNull(draft.estimateCapacity),
    crew_capacity_hours_per_week: toNumberOrNull(draft.crewHours),
    backlog_alert_weeks: toNumberOrNull(draft.backlogWeeks),
  };
}

function numberToDraft(value: number | null | undefined): string {
  return value === null || value === undefined ? "" : String(value);
}

function targetToDraft(target: RevenueTarget): PlanDraft {
  return {
    revenueGoal: numberToDraft(target.revenue_goal),
    avgJobValue: numberToDraft(target.target_avg_job_value),
    closeRate: numberToDraft(target.target_close_rate),
    satRate: numberToDraft(target.assumed_sat_rate),
    targetLeads: numberToDraft(target.target_leads),
    estimateCapacity: numberToDraft(target.estimate_capacity_per_month),
    crewHours: numberToDraft(target.crew_capacity_hours_per_week),
    backlogWeeks: numberToDraft(target.backlog_alert_weeks),
  };
}

/** Identity of a plan's *saved* values, so two drafts that store the same row compare equal. */
function planKey(draft: PlanDraft): string {
  return JSON.stringify(draftToPlan(draft));
}

// ---------------------------------------------------------------------------
// Month helpers
// ---------------------------------------------------------------------------

const MONTH_NAMES = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
] as const;

const MONTH_ABBR = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
] as const;

/** ISO first-of-month key, e.g. (2026, 6) -> "2026-06-01". */
function monthIso(year: number, month: number): string {
  return `${year}-${String(month).padStart(2, "0")}-01`;
}

/** True when this month has not finished yet, so planning it rewrites nothing. */
function isPlannable(year: number, month: number, today: Date): boolean {
  const currentYear = today.getFullYear();
  if (year !== currentYear) return year > currentYear;
  return month >= today.getMonth() + 1;
}

interface MonthDraft {
  month: number;
  /** null means "follows the default plan". */
  override: PlanDraft | null;
  /** The operator changed this month in this session, so save may write it. */
  touched: boolean;
  /** A target row already exists on the server for this month. */
  stored: boolean;
}

interface Seed {
  defaults: PlanDraft;
  months: MonthDraft[];
}

/**
 * Rebuild the editor state from a year of stored targets.
 *
 * The default is the plan shared by the most plannable months (ties break to
 * the earliest month), which is exactly what a previous save wrote; months that
 * differ from it are the overrides.
 */
export function seedFromTargets(
  targets: readonly RevenueTarget[],
  year: number,
  today: Date,
): Seed {
  const byMonth = new Map<number, RevenueTarget>();
  for (const target of targets) {
    const month = Number(target.period_month.slice(5, 7));
    if (month >= 1 && month <= 12) byMonth.set(month, target);
  }

  const plannable = [...byMonth.entries()].filter(([month]) =>
    isPlannable(year, month, today),
  );
  const pool = plannable.length > 0 ? plannable : [...byMonth.entries()];

  // Plurality vote on the stored plan, earliest month winning a tie.
  const tally = new Map<string, { count: number; draft: PlanDraft; month: number }>();
  for (const [month, target] of pool) {
    const draft = targetToDraft(target);
    const key = planKey(draft);
    const entry = tally.get(key);
    if (entry) entry.count += 1;
    else tally.set(key, { count: 1, draft, month });
  }
  let winner: { count: number; draft: PlanDraft; month: number } | null = null;
  for (const entry of tally.values()) {
    if (
      winner === null ||
      entry.count > winner.count ||
      (entry.count === winner.count && entry.month < winner.month)
    ) {
      winner = entry;
    }
  }

  const defaults = winner ? winner.draft : EMPTY_PLAN;
  const defaultKey = planKey(defaults);

  const months: MonthDraft[] = Array.from({ length: 12 }, (_, index) => {
    const month = index + 1;
    const target = byMonth.get(month);
    if (!target) {
      return { month, override: null, touched: false, stored: false };
    }
    const draft = targetToDraft(target);
    const differs = planKey(draft) !== defaultKey;
    return { month, override: differs ? draft : null, touched: false, stored: true };
  });

  return { defaults, months };
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function BacksolveReadoutPanel({
  draft,
  label,
}: {
  draft: PlanDraft;
  label: string;
}) {
  const readout = describeBacksolve(draftToInput(draft));

  return (
    <div
      role="status"
      aria-live="polite"
      className="rounded-lg border bg-muted/30 p-4"
    >
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      {readout.sentence !== "" && (
        <p className="mt-1 text-sm font-semibold text-foreground">
          {readout.sentence}
        </p>
      )}
      {readout.missing !== null && (
        <p className="mt-1 text-sm text-muted-foreground">{readout.missing}</p>
      )}
    </div>
  );
}

function PlanFields({
  idPrefix,
  draft,
  errors,
  disabled,
  onChange,
}: {
  idPrefix: string;
  draft: PlanDraft;
  errors: PlanErrors;
  disabled: boolean;
  onChange: (field: PlanField, value: string) => void;
}) {
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {PLAN_FIELDS.map((field) => {
        const id = `${idPrefix}-${field.key}`;
        const error = errors[field.key];
        return (
          <div key={field.key} className="space-y-2">
            <Label htmlFor={id}>{field.label}</Label>
            <Input
              id={id}
              type="number"
              inputMode="decimal"
              min={field.min}
              max={field.max}
              step={field.step}
              value={draft[field.key]}
              disabled={disabled}
              aria-invalid={error !== undefined}
              aria-describedby={`${id}-hint`}
              onChange={(event) => onChange(field.key, event.target.value)}
            />
            <p
              id={`${id}-hint`}
              className={
                error === undefined
                  ? "text-xs text-muted-foreground"
                  : "text-xs font-medium text-destructive"
              }
            >
              {error ?? field.hint}
            </p>
          </div>
        );
      })}
    </div>
  );
}

function MonthTile({
  month,
  label,
  goal,
  isOverride,
  isSelected,
  isPast,
  onSelect,
}: {
  month: number;
  label: string;
  goal: number | null;
  isOverride: boolean;
  isSelected: boolean;
  isPast: boolean;
  onSelect: (month: number) => void;
}) {
  // The override marker is a badge plus a left accent bar, never colour alone.
  const accent = isOverride ? "border-l-4 border-l-primary" : "border-l-4 border-l-transparent";
  const selection = isSelected ? "ring-2 ring-ring" : "";
  const state = isPast ? "bg-muted/40" : "bg-card";

  return (
    <button
      type="button"
      onClick={() => onSelect(month)}
      aria-pressed={isSelected}
      className={`flex flex-col items-start gap-1 rounded-lg border p-3 text-left transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${accent} ${state} ${selection}`}
    >
      <span className="flex w-full items-center justify-between gap-2">
        <span className="text-sm font-semibold">{label}</span>
        {isOverride && (
          <Badge variant="secondary" className="text-[10px]">
            Custom
          </Badge>
        )}
      </span>
      <span
        className={
          goal === null
            ? "text-sm text-muted-foreground"
            : "text-sm font-medium text-foreground"
        }
      >
        {goal === null ? "Not set" : formatWholeCurrency(goal)}
      </span>
      {isPast && (
        <span className="text-[11px] text-muted-foreground">Already recorded</span>
      )}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function SalesTargetsSettingsTab() {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();

  const [today] = useState(() => new Date());
  const [year, setYear] = useState(() => today.getFullYear());

  const { data, isPending } = useQuery({
    queryKey: queryKeys.revenueTargets.byYear(workspaceId ?? "", year),
    queryFn: () => revenueTargetsApi.list(workspaceId!, year),
    enabled: !!workspaceId,
    // The editable draft re-seeds whenever the fetched year's identity changes.
    // Keep the query stable so a background refetch can't return a fresh object
    // and silently wipe an operator's unsaved edits.
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });

  const [defaults, setDefaults] = useState<PlanDraft>(EMPTY_PLAN);
  const [months, setMonths] = useState<MonthDraft[]>(
    () => seedFromTargets([], new Date().getFullYear(), new Date()).months,
  );
  const [selectedMonth, setSelectedMonth] = useState<number | null>(null);
  const [seeded, setSeeded] = useState<{ source: RevenueTargetList; year: number } | null>(
    null,
  );

  // Seed/re-seed from the server, resetting when the fetched year's identity
  // changes (first load, year switch, or a save replacing the cached copy).
  // Adjusting state during render on an identity guard is the sanctioned React
  // pattern and avoids a cascading effect render.
  if (data && (seeded === null || seeded.source !== data || seeded.year !== year)) {
    const seed = seedFromTargets(data.items, year, today);
    setSeeded({ source: data, year });
    setDefaults(seed.defaults);
    setMonths(seed.months);
    setSelectedMonth(null);
  }

  const mutation = useMutation({
    mutationFn: (targets: RevenueTargetUpsert[]) =>
      revenueTargetsApi.bulkUpsert(workspaceId!, targets),
    onSuccess: (saved) => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.revenueTargets.all(workspaceId ?? ""),
      });
      toast.success(
        `Saved ${saved.total} ${saved.total === 1 ? "month" : "months"} of ${year}`,
      );
    },
    onError: (error: unknown) =>
      toast.error(getApiErrorMessage(error, "Failed to save sales targets")),
  });

  const defaultErrors = validatePlan(defaults);
  const monthErrors = new Map<number, PlanErrors>(
    months
      .filter((entry) => entry.override !== null)
      .map((entry) => [entry.month, validatePlan(entry.override as PlanDraft)]),
  );
  const hasErrors =
    Object.keys(defaultErrors).length > 0 ||
    [...monthErrors.values()].some((errors) => Object.keys(errors).length > 0);

  const writableMonths = months.filter(
    (entry) => entry.touched || isPlannable(year, entry.month, today),
  );

  const patchDefaults = (field: PlanField, value: string) =>
    setDefaults((prev) => ({ ...prev, [field]: value }));

  const patchMonth = (month: number, field: PlanField, value: string) =>
    setMonths((prev) =>
      prev.map((entry) =>
        entry.month === month && entry.override !== null
          ? {
              ...entry,
              touched: true,
              override: { ...entry.override, [field]: value },
            }
          : entry,
      ),
    );

  const customizeMonth = (month: number) =>
    setMonths((prev) =>
      prev.map((entry) =>
        entry.month === month
          ? { ...entry, touched: true, override: { ...defaults } }
          : entry,
      ),
    );

  const resetMonth = (month: number) =>
    setMonths((prev) =>
      prev.map((entry) =>
        entry.month === month ? { ...entry, touched: true, override: null } : entry,
      ),
    );

  const save = () => {
    const payload: RevenueTargetUpsert[] = writableMonths.map((entry) => ({
      period_month: monthIso(year, entry.month),
      ...draftToPlan(entry.override ?? defaults),
    }));
    if (payload.length === 0) {
      toast.error("Nothing to save: every month of this year has already passed.");
      return;
    }
    mutation.mutate(payload);
  };

  if (!workspaceId || (isPending && !data)) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="size-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const disabled = mutation.isPending;
  const yearOptions = [today.getFullYear() - 1, today.getFullYear(), today.getFullYear() + 1];
  const selected = months.find((entry) => entry.month === selectedMonth) ?? null;
  const selectedPlan = selected ? (selected.override ?? defaults) : null;
  const overrideCount = months.filter((entry) => entry.override !== null).length;

  return (
    <div className="space-y-6">
      {/* Default plan + live backsolve */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Target className="size-5" /> Default month plan
          </CardTitle>
          <CardDescription>
            The plan applied to every month from this month on, unless you give a
            month its own numbers below. Saving writes a target for each of those
            months, which is what the dashboard measures the month against.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <PlanFields
            idPrefix="sales-target-default"
            draft={defaults}
            errors={defaultErrors}
            disabled={disabled}
            onChange={patchDefaults}
          />
          <BacksolveReadoutPanel
            draft={defaults}
            label="What this goal takes"
          />
        </CardContent>
      </Card>

      {/* The seasonal year */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <CalendarRange className="size-5" /> Monthly plan
          </CardTitle>
          <CardDescription>
            Exteriors work is seasonal, so a flat monthly goal is wrong most of
            the year. Pick a month to give it its own numbers. Months marked
            Custom override the default; the rest follow it.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="flex flex-wrap items-end gap-4">
            <div className="space-y-2">
              <Label htmlFor="sales-target-year">Planning year</Label>
              <Select
                value={String(year)}
                onValueChange={(value) => setYear(Number(value))}
                disabled={disabled}
              >
                <SelectTrigger id="sales-target-year" className="w-36">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {yearOptions.map((option) => (
                    <SelectItem key={option} value={String(option)}>
                      {option}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <p className="text-sm text-muted-foreground">
              {overrideCount === 0
                ? "Every month follows the default plan."
                : `${overrideCount} of 12 months override the default.`}
            </p>
          </div>

          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">
            {months.map((entry) => {
              const plan = entry.override ?? defaults;
              const goal = toNumberOrNull(plan.revenueGoal);
              const past = !isPlannable(year, entry.month, today);
              return (
                <MonthTile
                  key={entry.month}
                  month={entry.month}
                  label={`${MONTH_ABBR[entry.month - 1]} ${year}`}
                  goal={past && !entry.stored && !entry.touched ? null : goal}
                  isOverride={entry.override !== null}
                  isSelected={selectedMonth === entry.month}
                  isPast={past}
                  onSelect={setSelectedMonth}
                />
              );
            })}
          </div>

          <Separator />

          {selected === null || selectedPlan === null ? (
            <p className="text-sm text-muted-foreground">
              Select a month above to give it its own goal and assumptions.
            </p>
          ) : (
            <div className="space-y-4 rounded-lg border bg-muted/20 p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="space-y-1">
                  <h3 className="text-base font-semibold">
                    {MONTH_NAMES[selected.month - 1]} {year}
                  </h3>
                  <p className="text-sm text-muted-foreground">
                    {selected.override === null
                      ? "Follows the default month plan."
                      : "Overrides the default month plan."}
                  </p>
                </div>
                {selected.override === null ? (
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => customizeMonth(selected.month)}
                    disabled={disabled}
                  >
                    Give {MONTH_NAMES[selected.month - 1]} its own plan
                  </Button>
                ) : (
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => resetMonth(selected.month)}
                    disabled={disabled}
                  >
                    <RotateCcw className="size-4" /> Reset to default
                  </Button>
                )}
              </div>

              {!isPlannable(year, selected.month, today) && (
                <p className="text-sm font-medium text-warning">
                  This month has already been recorded. It is only rewritten if
                  you change it here.
                </p>
              )}

              {selected.override === null ? (
                <PlanFields
                  idPrefix={`sales-target-month-${selected.month}-readonly`}
                  draft={defaults}
                  errors={{}}
                  disabled
                  onChange={() => undefined}
                />
              ) : (
                <PlanFields
                  idPrefix={`sales-target-month-${selected.month}`}
                  draft={selected.override}
                  errors={monthErrors.get(selected.month) ?? {}}
                  disabled={disabled}
                  onChange={(field, value) => patchMonth(selected.month, field, value)}
                />
              )}

              <BacksolveReadoutPanel
                draft={selectedPlan}
                label={`What ${MONTH_NAMES[selected.month - 1]} takes`}
              />
            </div>
          )}
        </CardContent>
      </Card>

      {/* Save */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">
          Saving writes {writableMonths.length} of 12 months. Months that have
          already passed keep the goal they were set with unless you edit them.
        </p>
        <Button onClick={save} disabled={disabled || hasErrors}>
          {mutation.isPending ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <Save className="size-4" />
          )}
          Save sales targets
        </Button>
      </div>
    </div>
  );
}
