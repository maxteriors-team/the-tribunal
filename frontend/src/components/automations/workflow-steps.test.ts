/**
 * Authoring rules for multi-step workflows.
 *
 * These assertions exist to keep the editor and the backend engine agreeing on
 * one stored shape. Where they disagree the operator sees one thing and the
 * customer receives another, so the cases that matter most are the ones the
 * engine treats specially: `null` vs `__end__` goto targets, ids that must
 * never be rewritten, and duration keys that must replace rather than sum.
 */

import { describe, expect, it } from "vitest";

import type { AutomationAction } from "@/types";

import {
  GOTO_END,
  GOTO_NEXT_VALUE,
  applyBranchConfig,
  applyWaitConfig,
  branchTargetSelectValue,
  describeBranchStep,
  describeWaitStep,
  isDanglingTarget,
  isWaitAction,
  newStepId,
  normalizeSteps,
  parseBranchConfig,
  parseWaitConfig,
  setBranchTarget,
  stepSelectValue,
  validateSteps,
} from "./workflow-steps";

const step = (
  type: AutomationAction["type"],
  config: Record<string, unknown> = {},
  id?: string
): AutomationAction => (id ? { id, type, config } : { type, config });

describe("wait steps", () => {
  it("defaults to the engine's one-hour fallback", () => {
    expect(parseWaitConfig(undefined)).toEqual({ amount: 1, unit: "hours" });
    expect(parseWaitConfig({})).toEqual({ amount: 1, unit: "hours" });
  });

  it("keeps the operator's own unit", () => {
    expect(parseWaitConfig({ days: 3 })).toEqual({ amount: 3, unit: "days" });
    expect(parseWaitConfig({ minutes: 45 })).toEqual({ amount: 45, unit: "minutes" });
  });

  it("preserves an explicit zero", () => {
    expect(parseWaitConfig({ hours: 0 })).toEqual({ amount: 0, unit: "hours" });
  });

  it("folds a multi-unit config into an exact single unit", () => {
    // The engine sums units, so 1d + 12h is 36h — not 1, and not 12.
    expect(parseWaitConfig({ days: 1, hours: 12 })).toEqual({ amount: 36, unit: "hours" });
  });

  it("drops negative durations rather than firing immediately", () => {
    expect(parseWaitConfig({ hours: -5 })).toEqual({ amount: 1, unit: "hours" });
  });

  it("ignores unparseable values", () => {
    expect(parseWaitConfig({ hours: "abc" })).toEqual({ amount: 1, unit: "hours" });
  });

  it("replaces other duration keys instead of adding to them", () => {
    // A leftover `hours` would be summed with the new `days` by the engine.
    expect(applyWaitConfig({ hours: 6 }, { amount: 2, unit: "days" })).toEqual({ days: 2 });
  });

  it("round-trips through apply and parse", () => {
    const config = applyWaitConfig({}, { amount: 30, unit: "minutes" });
    expect(parseWaitConfig(config)).toEqual({ amount: 30, unit: "minutes" });
  });

  it("summarises with correct pluralisation", () => {
    expect(describeWaitStep({ days: 1 })).toBe("1 day");
    expect(describeWaitStep({ days: 2 })).toBe("2 days");
  });

  it("treats the legacy delay spelling as a wait", () => {
    expect(isWaitAction("delay")).toBe(true);
    expect(isWaitAction("wait")).toBe(true);
    expect(isWaitAction("send_sms")).toBe(false);
  });
});

describe("branch config", () => {
  it("reads the canonical conditions/logic keys", () => {
    const parsed = parseBranchConfig({
      conditions: [{ field: "first_name", operator: "equals", value: "Ada" }],
      logic: "or",
      then_goto: "abc",
      else_goto: GOTO_END,
    });
    expect(parsed.filters).toEqual({
      logic: "or",
      rules: [{ field: "first_name", operator: "equals", value: "Ada" }],
    });
    expect(parsed.thenGoto).toBe("abc");
    expect(parsed.elseGoto).toBe(GOTO_END);
  });

  it("tolerates the segment-style aliases the backend also accepts", () => {
    const parsed = parseBranchConfig({
      filter_rules: [{ field: "lead_score", operator: "greater_than", value: 50 }],
      filter_logic: "any",
    });
    expect(parsed.filters?.logic).toBe("or");
    expect(parsed.filters?.rules).toHaveLength(1);
  });

  it("accepts a lone rule written as a bare object", () => {
    const parsed = parseBranchConfig({
      conditions: { field: "city", operator: "equals", value: "Austin" },
    });
    expect(parsed.filters?.rules).toHaveLength(1);
  });

  it("drops malformed rules", () => {
    const parsed = parseBranchConfig({ conditions: [{ operator: "equals" }, "junk", null] });
    expect(parsed.filters).toBeNull();
  });

  it("clears the aliases on write so the two spellings cannot disagree", () => {
    const next = applyBranchConfig(
      { filter_rules: [{ field: "old", operator: "equals", value: "x" }], filter_logic: "or" },
      { filters: { logic: "and", rules: [] }, thenGoto: null, elseGoto: null }
    );
    expect(next.filter_rules).toBeUndefined();
    expect(next.filter_logic).toBeUndefined();
    expect(next.conditions).toEqual([]);
  });

  it("writes null for a fall-through target", () => {
    // null means "next step"; __end__ means "stop". Collapsing them is a bug.
    const next = applyBranchConfig({}, { filters: null, thenGoto: null, elseGoto: GOTO_END });
    expect(next.then_goto).toBeNull();
    expect(next.else_goto).toBe(GOTO_END);
  });

  it("summarises the condition count", () => {
    expect(describeBranchStep({})).toBe("Always yes");
    expect(
      describeBranchStep({ conditions: [{ field: "a", operator: "equals", value: 1 }] })
    ).toBe("1 condition");
  });
});

describe("branch targets", () => {
  it("assigns an id to a step the first time it becomes a target", () => {
    const steps = [step("branch"), step("send_sms")];
    const next = setBranchTarget(steps, 0, "thenGoto", stepSelectValue(1));
    expect(next[1]?.id).toBeTruthy();
    expect(parseBranchConfig(next[0]?.config).thenGoto).toBe(next[1]?.id);
  });

  it("never rewrites an existing id", () => {
    // Other branches and half-finished runs already refer to it.
    const steps = [step("branch"), step("send_sms", {}, "keepme")];
    const next = setBranchTarget(steps, 0, "elseGoto", stepSelectValue(1));
    expect(next[1]?.id).toBe("keepme");
    expect(parseBranchConfig(next[0]?.config).elseGoto).toBe("keepme");
  });

  it("stores the end sentinel without giving any step an id", () => {
    const steps = [step("branch"), step("send_sms")];
    const next = setBranchTarget(steps, 0, "thenGoto", GOTO_END);
    expect(parseBranchConfig(next[0]?.config).thenGoto).toBe(GOTO_END);
    expect(next[1]?.id).toBeUndefined();
  });

  it("stores null for the fall-through choice", () => {
    const steps = [step("branch"), step("send_sms")];
    const next = setBranchTarget(steps, 0, "thenGoto", GOTO_NEXT_VALUE);
    expect(parseBranchConfig(next[0]?.config).thenGoto).toBeNull();
  });

  it("maps a stored target back to its select value", () => {
    const steps = [step("branch"), step("send_sms", {}, "abc")];
    expect(branchTargetSelectValue(steps, "abc")).toBe(stepSelectValue(1));
    expect(branchTargetSelectValue(steps, null)).toBe(GOTO_NEXT_VALUE);
    expect(branchTargetSelectValue(steps, GOTO_END)).toBe(GOTO_END);
    expect(branchTargetSelectValue(steps, "gone")).toBe("");
  });

  it("detects a target whose step was deleted", () => {
    const steps = [step("branch"), step("send_sms", {}, "abc")];
    expect(isDanglingTarget(steps, "abc")).toBe(false);
    expect(isDanglingTarget(steps, "gone")).toBe(true);
    expect(isDanglingTarget(steps, null)).toBe(false);
    expect(isDanglingTarget(steps, GOTO_END)).toBe(false);
  });

  it("generates ids within the backend's 64-char limit", () => {
    const id = newStepId();
    expect(id.length).toBeGreaterThan(0);
    expect(id.length).toBeLessThanOrEqual(64);
  });
});

describe("normalizeSteps", () => {
  it("omits an absent id so the stored shape matches the backend's", () => {
    expect(normalizeSteps([step("send_sms", { message: "hi" })])[0]).not.toHaveProperty("id");
  });

  it("keeps a real id", () => {
    expect(normalizeSteps([step("send_sms", {}, "abc")])[0]?.id).toBe("abc");
  });

  it("drops a blank id", () => {
    expect(normalizeSteps([step("send_sms", {}, "   ")])[0]).not.toHaveProperty("id");
  });

  it("trims tag values", () => {
    expect(normalizeSteps([step("apply_tag", { tag: "  hot  " })])[0]?.config.tag).toBe("hot");
  });
});

describe("validateSteps", () => {
  it("requires at least one step", () => {
    expect(validateSteps([])).toBe("Add at least one step.");
  });

  it("requires a tag value", () => {
    expect(validateSteps([step("apply_tag", { tag: "" })])).toContain("enter a tag");
  });

  it("rejects a dangling branch target", () => {
    // The engine ends the run here, dropping the customer mid-sequence.
    const steps = [step("branch", { then_goto: "gone", else_goto: null })];
    expect(validateSteps(steps)).toContain("no longer exists");
  });

  it("accepts a valid branch", () => {
    const steps = [step("branch", { then_goto: "abc", else_goto: GOTO_END }), step("send_sms", {}, "abc")];
    expect(validateSteps(steps)).toBeNull();
  });

  it("accepts a branch that falls through on both sides", () => {
    expect(validateSteps([step("branch", { then_goto: null, else_goto: null })])).toBeNull();
  });
});
