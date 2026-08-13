/**
 * Authoring rules for multi-step workflows — `wait` durations, `branch`
 * conditions, and the stable step ids branches jump to.
 *
 * Pure functions over plain values (no React, no I/O) so they can be unit
 * tested the way `backlog-trigger.ts` is. They mirror the backend engine
 * (`app/services/automations/runner.py` and `branching.py`) key for key: what
 * this file writes into a step's config is exactly what that engine reads back
 * out, including the tolerated legacy spellings.
 */

import type {
  AutomationAction,
  AutomationActionType,
  AutomationGotoTarget,
  FilterDefinition,
  FilterRule,
} from "@/types";

/** Goto target meaning "finish the run" (`runner.GOTO_END`). */
export const GOTO_END = "__end__";

/**
 * `<Select>` value standing in for the `null` goto ("fall through to the next
 * step"). Radix cannot hold `null` or `""` as an item value, so the intent
 * needs a token of its own — collapsing it into `"__end__"` would silently
 * turn "carry on" into "stop".
 */
export const GOTO_NEXT_VALUE = "__next__";

const STEP_VALUE_PREFIX = "step:";

/** Action types that apply a tag; both spellings are accepted by the backend. */
export const TAG_ACTIONS: readonly AutomationActionType[] = ["apply_tag", "add_tag"];

/** Action types that pause the run. `delay` is the legacy spelling of `wait`. */
export const WAIT_ACTIONS: readonly AutomationActionType[] = ["wait", "delay"];

export const WAIT_UNITS = ["minutes", "hours", "days"] as const;

export type WaitUnit = (typeof WAIT_UNITS)[number];

export const WAIT_UNIT_LABELS: Record<WaitUnit, string> = {
  minutes: "Minutes",
  hours: "Hours",
  days: "Days",
};

const WAIT_UNIT_SINGULAR: Record<WaitUnit, string> = {
  minutes: "minute",
  hours: "hour",
  days: "day",
};

const MINUTES_PER_UNIT: Record<WaitUnit, number> = {
  minutes: 1,
  hours: 60,
  days: 1440,
};

/** What a `wait` step with no duration configured actually waits. */
const DEFAULT_WAIT_INPUTS: WaitInputs = { amount: 1, unit: "hours" };

export interface WaitInputs {
  amount: number;
  unit: WaitUnit;
}

export interface BranchInputs {
  filters: FilterDefinition | null;
  thenGoto: AutomationGotoTarget;
  elseGoto: AutomationGotoTarget;
}

type StepConfig = Record<string, unknown>;

function isRecord(value: unknown): value is StepConfig {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** A trimmed non-empty string, or null. */
function readString(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

/**
 * A finite, non-negative number, or null. Negative durations are dropped
 * rather than clamped, matching the engine: a bad value must make the run wait
 * longer, never fire immediately.
 */
function readAmount(value: unknown): number | null {
  if (typeof value === "boolean" || value === null || value === undefined) return null;
  const amount = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(amount) || amount < 0) return null;
  return amount;
}

export function isTagAction(type: AutomationActionType): boolean {
  return TAG_ACTIONS.includes(type);
}

export function isWaitAction(type: AutomationActionType): boolean {
  return WAIT_ACTIONS.includes(type);
}

/**
 * Read a `wait` step's config back into the single amount + unit the editor
 * shows. A config carrying several units (the engine sums them) is folded into
 * the largest unit that represents the total exactly, so `{days: 1, hours: 12}`
 * reads as 36 hours rather than losing half of itself.
 */
export function parseWaitConfig(config: StepConfig | undefined): WaitInputs {
  const present = WAIT_UNITS.map((unit) => ({ unit, amount: readAmount(config?.[unit]) })).filter(
    (entry): entry is { unit: WaitUnit; amount: number } => entry.amount !== null
  );

  if (present.length === 0) return { ...DEFAULT_WAIT_INPUTS };

  const [only] = present;
  // One unit: keep the operator's own unit, including an explicit zero.
  if (present.length === 1 && only) return { amount: only.amount, unit: only.unit };

  const totalMinutes = present.reduce(
    (total, entry) => total + entry.amount * MINUTES_PER_UNIT[entry.unit],
    0
  );
  if (totalMinutes > 0 && totalMinutes % MINUTES_PER_UNIT.days === 0) {
    return { amount: totalMinutes / MINUTES_PER_UNIT.days, unit: "days" };
  }
  if (totalMinutes > 0 && totalMinutes % MINUTES_PER_UNIT.hours === 0) {
    return { amount: totalMinutes / MINUTES_PER_UNIT.hours, unit: "hours" };
  }
  return { amount: totalMinutes, unit: "minutes" };
}

/**
 * Write amount + unit back into a step config, dropping the other duration
 * keys: the engine sums every unit it finds, so a leftover `hours` from a
 * previous edit would be added to the new `days` instead of replaced by it.
 */
export function applyWaitConfig(config: StepConfig, inputs: WaitInputs): StepConfig {
  const next: StepConfig = { ...config };
  for (const unit of WAIT_UNITS) delete next[unit];
  next[inputs.unit] = Math.max(0, inputs.amount);
  return next;
}

/** Short human summary of a wait step, e.g. "2 hours". */
export function describeWaitStep(config: StepConfig | undefined): string {
  const { amount, unit } = parseWaitConfig(config);
  return `${amount} ${amount === 1 ? WAIT_UNIT_SINGULAR[unit] : unit}`;
}

function toFilterValue(raw: unknown): FilterRule["value"] {
  if (typeof raw === "string" || typeof raw === "number" || typeof raw === "boolean") return raw;
  if (Array.isArray(raw)) {
    if (raw.every((entry): entry is string => typeof entry === "string")) return raw;
    if (raw.every((entry): entry is number => typeof entry === "number")) return raw;
  }
  return "";
}

function toFilterRule(raw: unknown): FilterRule | null {
  if (!isRecord(raw)) return null;
  const field = readString(raw.field);
  const operator = readString(raw.operator);
  if (!field || !operator) return null;
  return { field, operator, value: toFilterValue(raw.value) };
}

function toGotoTarget(raw: unknown): AutomationGotoTarget {
  return readString(raw);
}

/**
 * Read a `branch` step's config. Tolerates the shapes the column actually
 * arrives in — the `filter_rules`/`filter_logic` spelling shared with segments,
 * a lone rule written as a bare object, `all`/`any` combinators — the same way
 * `branching.parse_branch_condition` does.
 */
export function parseBranchConfig(config: StepConfig | undefined): BranchInputs {
  const rawRules = config?.conditions ?? config?.filter_rules;
  const rawList = isRecord(rawRules) ? [rawRules] : Array.isArray(rawRules) ? rawRules : [];
  const rules = rawList
    .map(toFilterRule)
    .filter((rule): rule is FilterRule => rule !== null);

  const rawLogic = readString(config?.logic ?? config?.filter_logic)?.toLowerCase();
  const logic: FilterDefinition["logic"] = rawLogic === "or" || rawLogic === "any" ? "or" : "and";

  return {
    filters: rules.length > 0 ? { logic, rules } : null,
    thenGoto: toGotoTarget(config?.then_goto),
    elseGoto: toGotoTarget(config?.else_goto),
  };
}

/**
 * Write branch inputs back into a step config. Writes the canonical
 * `conditions`/`logic` keys and clears the segment-style aliases so the two
 * spellings can never disagree about what the branch asks.
 */
export function applyBranchConfig(config: StepConfig, inputs: BranchInputs): StepConfig {
  const next: StepConfig = { ...config };
  delete next.filter_rules;
  delete next.filter_logic;
  next.conditions = inputs.filters?.rules ?? [];
  next.logic = inputs.filters?.logic ?? "and";
  next.then_goto = inputs.thenGoto;
  next.else_goto = inputs.elseGoto;
  return next;
}

/** Short human summary of a branch step's condition count. */
export function describeBranchStep(config: StepConfig | undefined): string {
  const rules = parseBranchConfig(config).filters?.rules ?? [];
  if (rules.length === 0) return "Always yes";
  return rules.length === 1 ? "1 condition" : `${rules.length} conditions`;
}

/**
 * A new step id. Short on purpose: it is typed into config by hand often enough
 * (assistant-authored workflows, fixtures) that a full uuid is noise, and the
 * backend caps the field at 64 chars.
 */
export function newStepId(): string {
  return crypto.randomUUID().slice(0, 8);
}

export function stepSelectValue(index: number): string {
  return `${STEP_VALUE_PREFIX}${index}`;
}

/** The `<Select>` value for a stored goto target, or "" when it dangles. */
export function branchTargetSelectValue(
  steps: AutomationAction[],
  target: AutomationGotoTarget
): string {
  if (target === null) return GOTO_NEXT_VALUE;
  if (target === GOTO_END) return GOTO_END;
  const index = steps.findIndex((step) => step.id === target);
  return index === -1 ? "" : stepSelectValue(index);
}

/** Whether a target names a step that is no longer in the workflow. */
export function isDanglingTarget(
  steps: AutomationAction[],
  target: AutomationGotoTarget
): boolean {
  if (target === null || target === GOTO_END) return false;
  return !steps.some((step) => step.id === target);
}

/**
 * Point one side of a branch at the step the operator picked.
 *
 * Targets are chosen by position, so the step being pointed at gets an id the
 * first time it becomes a target. An id that already exists is never rewritten:
 * other branches and half-finished runs refer to it.
 */
export function setBranchTarget(
  steps: AutomationAction[],
  branchIndex: number,
  side: "thenGoto" | "elseGoto",
  selectValue: string
): AutomationAction[] {
  const branchStep = steps[branchIndex];
  if (!branchStep) return steps;

  const next = [...steps];
  let target: AutomationGotoTarget = null;

  if (selectValue === GOTO_END) {
    target = GOTO_END;
  } else if (selectValue.startsWith(STEP_VALUE_PREFIX)) {
    const targetIndex = Number.parseInt(selectValue.slice(STEP_VALUE_PREFIX.length), 10);
    const targetStep = next[targetIndex];
    if (targetStep) {
      const id = readString(targetStep.id) ?? newStepId();
      next[targetIndex] = { ...targetStep, id };
      target = id;
    }
  }

  const inputs = parseBranchConfig(branchStep.config);
  const nextInputs: BranchInputs =
    side === "thenGoto" ? { ...inputs, thenGoto: target } : { ...inputs, elseGoto: target };
  const updated = next[branchIndex] ?? branchStep;
  next[branchIndex] = { ...updated, config: applyBranchConfig(updated.config, nextInputs) };
  return next;
}

/**
 * Clean the authored steps for the API: trim tag values and drop an empty id
 * so a step nothing points at stays id-less, exactly as the backend stores it.
 */
export function normalizeSteps(steps: AutomationAction[]): AutomationAction[] {
  return steps.map((step) => {
    const config: StepConfig = { ...step.config };
    if (typeof config.tag === "string") config.tag = config.tag.trim();
    const id = readString(step.id);
    const normalized: AutomationAction = { type: step.type, config };
    return id ? { ...normalized, id } : normalized;
  });
}

/**
 * The first problem that would make a workflow misbehave once saved, or null.
 *
 * A dangling branch target is treated as an error rather than a warning: the
 * engine stops the run when it hits one, which in this product means a customer
 * silently falls out of the sequence mid-conversation.
 */
export function validateSteps(steps: AutomationAction[]): string | null {
  if (steps.length === 0) return "Add at least one step.";

  for (const [index, step] of steps.entries()) {
    const where = `Step ${index + 1}`;

    if (isTagAction(step.type) && !readString(step.config.tag)) {
      return `${where}: enter a tag to apply.`;
    }
    if (step.type === "move_to_stage" && !readString(step.config.stage_id)) {
      return `${where}: choose a stage to move the deal to.`;
    }
    if (step.type === "start_drip_campaign" && !readString(step.config.drip_campaign_id)) {
      return `${where}: choose a drip campaign to start.`;
    }
    if (step.type === "branch") {
      const { thenGoto, elseGoto } = parseBranchConfig(step.config);
      const sides: [string, AutomationGotoTarget][] = [
        ["If yes", thenGoto],
        ["If no", elseGoto],
      ];
      for (const [label, target] of sides) {
        if (isDanglingTarget(steps, target)) {
          return `${where}: "${label}" points at a step that no longer exists — pick a new target.`;
        }
      }
    }
  }

  return null;
}
