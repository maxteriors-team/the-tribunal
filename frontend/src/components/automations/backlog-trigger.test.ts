import { describe, expect, it } from "vitest";

import {
  BACKLOG_DEFAULT_COOLDOWN_DAYS,
  BACKLOG_DEFAULT_THRESHOLD_WEEKS,
  buildBacklogTriggerConfig,
  defaultBacklogTriggerInputs,
  describeBacklogTrigger,
  parseBacklogTriggerConfig,
  validateBacklogTriggerInputs,
} from "@/components/automations/backlog-trigger";

describe("backlog trigger defaults", () => {
  it("offers the home-service threshold and a real cooldown", () => {
    expect(defaultBacklogTriggerInputs()).toEqual({
      thresholdWeeks: "4",
      cooldownDays: "14",
    });
    expect(BACKLOG_DEFAULT_THRESHOLD_WEEKS).toBe(4);
    expect(BACKLOG_DEFAULT_COOLDOWN_DAYS).toBe(14);
  });
});

describe("buildBacklogTriggerConfig", () => {
  it("writes the trigger_config keys the worker reads", () => {
    expect(
      buildBacklogTriggerConfig({ thresholdWeeks: "2.5", cooldownDays: "7" }),
    ).toEqual({ threshold_weeks: 2.5, cooldown_days: 7 });
  });
});

describe("validateBacklogTriggerInputs", () => {
  it("accepts a positive threshold and a whole-day cooldown", () => {
    expect(
      validateBacklogTriggerInputs({ thresholdWeeks: "4", cooldownDays: "14" }),
    ).toBeNull();
  });

  it.each(["", "0", "-2", "abc"])(
    "rejects a threshold of %s",
    (thresholdWeeks) => {
      expect(
        validateBacklogTriggerInputs({ thresholdWeeks, cooldownDays: "14" }),
      ).toMatch(/threshold/i);
    },
  );

  it.each(["", "0", "-1", "1.5", "nope"])(
    "rejects a cooldown of %s — an uncapped re-fire would spam the list",
    (cooldownDays) => {
      expect(
        validateBacklogTriggerInputs({ thresholdWeeks: "4", cooldownDays }),
      ).toMatch(/cooldown/i);
    },
  );
});

describe("parseBacklogTriggerConfig", () => {
  it("hydrates a stored config", () => {
    expect(
      parseBacklogTriggerConfig({ threshold_weeks: 6, cooldown_days: 30 }),
    ).toEqual({ thresholdWeeks: "6", cooldownDays: "30" });
  });

  it("falls back to defaults for an automation that never set them", () => {
    expect(parseBacklogTriggerConfig(undefined)).toEqual({
      thresholdWeeks: "4",
      cooldownDays: "14",
    });
    expect(parseBacklogTriggerConfig({ threshold_weeks: 0, cooldown_days: 0 })).toEqual({
      thresholdWeeks: "4",
      cooldownDays: "14",
    });
  });
});

describe("describeBacklogTrigger", () => {
  it("summarises the threshold and cooldown for the card", () => {
    expect(
      describeBacklogTrigger({ threshold_weeks: 4, cooldown_days: 14 }),
    ).toBe("Below 4 weeks · 14-day cooldown");
  });

  it("singularises one week", () => {
    expect(describeBacklogTrigger({ threshold_weeks: 1, cooldown_days: 7 })).toBe(
      "Below 1 week · 7-day cooldown",
    );
  });
});
