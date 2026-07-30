/**
 * Builder helpers for the `backlog_below_threshold` trigger.
 *
 * The trigger closes the loop between the fuel gauge (weeks of booked work) and
 * demand generation: when the backlog drops under `threshold_weeks`, the
 * automation's actions fire, then stay silent for `cooldown_days`.
 *
 * Kept out of the page component so the two rules the backend depends on — a
 * positive threshold and a cooldown of at least one day — are unit-testable
 * without driving a dialog. Defaults mirror
 * `backend/app/services/automations/conditions.py`.
 */

/** Weeks of booked work below which home-service owners start marketing. */
export const BACKLOG_DEFAULT_THRESHOLD_WEEKS = 4;

/** Days of silence after a fire (`DEFAULT_BACKLOG_COOLDOWN_DAYS`). */
export const BACKLOG_DEFAULT_COOLDOWN_DAYS = 14;

export interface BacklogTriggerInputs {
  thresholdWeeks: string;
  cooldownDays: string;
}

/** Form defaults for a brand-new backlog automation. */
export function defaultBacklogTriggerInputs(): BacklogTriggerInputs {
  return {
    thresholdWeeks: String(BACKLOG_DEFAULT_THRESHOLD_WEEKS),
    cooldownDays: String(BACKLOG_DEFAULT_COOLDOWN_DAYS),
  };
}

/**
 * Hydrate the form from a stored `trigger_config`, falling back to the defaults
 * for values an older automation (or the API) never set.
 */
export function parseBacklogTriggerConfig(
  config: Record<string, unknown> | undefined
): BacklogTriggerInputs {
  const threshold = Number(config?.threshold_weeks);
  const cooldown = Number(config?.cooldown_days);
  return {
    thresholdWeeks: String(
      Number.isFinite(threshold) && threshold > 0
        ? threshold
        : BACKLOG_DEFAULT_THRESHOLD_WEEKS
    ),
    cooldownDays: String(
      Number.isFinite(cooldown) && cooldown >= 1
        ? Math.floor(cooldown)
        : BACKLOG_DEFAULT_COOLDOWN_DAYS
    ),
  };
}

/**
 * Reject input the backend would have to silently default away. Returns an error
 * message for the toast, or `null` when the inputs are usable.
 */
export function validateBacklogTriggerInputs(
  inputs: BacklogTriggerInputs
): string | null {
  const threshold = Number(inputs.thresholdWeeks);
  if (!Number.isFinite(threshold) || threshold <= 0) {
    return "Enter a backlog threshold greater than 0 weeks";
  }
  const cooldown = Number(inputs.cooldownDays);
  if (!Number.isInteger(cooldown) || cooldown < 1) {
    return "Enter a cooldown of at least 1 day";
  }
  return null;
}

/** The `trigger_config` the worker reads: `{ threshold_weeks, cooldown_days }`. */
export function buildBacklogTriggerConfig(
  inputs: BacklogTriggerInputs
): { threshold_weeks: number; cooldown_days: number } {
  return {
    threshold_weeks: Number(inputs.thresholdWeeks),
    cooldown_days: Number(inputs.cooldownDays),
  };
}

/** One-line summary for the automation card, e.g. "Below 4 weeks · 14-day cooldown". */
export function describeBacklogTrigger(
  config: Record<string, unknown> | undefined
): string {
  const { thresholdWeeks, cooldownDays } = parseBacklogTriggerConfig(config);
  const weeks = Number(thresholdWeeks);
  return `Below ${weeks} ${weeks === 1 ? "week" : "weeks"} · ${cooldownDays}-day cooldown`;
}
