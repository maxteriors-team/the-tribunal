"use client";

/**
 * The technician's own selling scoreboard, shown on the job-picker screen.
 *
 * Sits under the job list rather than above it: the job is the reason the
 * technician opened the app, and their numbers are what they check on the way
 * past. Leading with the scoreboard would put a performance review in front of
 * someone trying to start work.
 *
 * **Their numbers only.** No colleague appears here, by construction — the
 * endpoint has no user parameter. A leaderboard is an owner's decision to make
 * deliberately, not something the narrowest tier in the product leaks by
 * default.
 *
 * The rank ladder renders only when the workspace configured one. With no ranks
 * the facts still show, because sold/approved/close-rate are facts while rank
 * names and payouts are somebody's compensation policy.
 */

import type { UpsellMyStats } from "@/lib/api/upsell";
import { formatCurrency } from "@/lib/utils/number";

interface UpsellScoreboardProps {
  stats: UpsellMyStats;
}

function formatMonth(iso: string): string {
  const parsed = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return "";
  return parsed.toLocaleDateString(undefined, { month: "long" });
}

export function UpsellScoreboard({ stats }: UpsellScoreboardProps) {
  const rank = stats.rank;
  const hasSold = stats.proposals_sent > 0;

  return (
    <section
      aria-labelledby="upsell-scoreboard-heading"
      className="mt-8 rounded-lg border bg-card p-4"
    >
      <div className="flex items-baseline justify-between gap-3">
        <h2 id="upsell-scoreboard-heading" className="font-medium">
          Your {formatMonth(stats.period_start)}
        </h2>
        {rank?.current_name ? (
          <span className="rounded-full border border-primary/40 bg-accent/40 px-2 py-0.5 text-xs font-medium">
            {rank.current_name}
          </span>
        ) : null}
      </div>

      {hasSold ? (
        <>
          <dl className="mt-3 grid grid-cols-3 gap-3">
            <div>
              <dt className="text-xs text-muted-foreground">Sold</dt>
              <dd className="text-lg font-semibold tabular-nums">
                {formatCurrency(stats.revenue_approved)}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Approved</dt>
              <dd className="text-lg font-semibold tabular-nums">
                {stats.proposals_approved}/{stats.proposals_sent}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Care plans</dt>
              <dd className="text-lg font-semibold tabular-nums">
                {stats.care_plans_sold}
              </dd>
            </div>
          </dl>

          {rank?.next_name && rank.amount_to_next !== null ? (
            <div className="mt-4">
              <div className="flex items-baseline justify-between gap-3 text-sm">
                <span className="text-muted-foreground">
                  {formatCurrency(rank.amount_to_next ?? 0)} to {rank.next_name}
                </span>
                {rank.next_reward ? (
                  <span className="font-medium">{rank.next_reward}</span>
                ) : null}
              </div>
              {/* Native progress element: announced by screen readers without a
                  hand-rolled role/aria-value trio, and honours forced colors. */}
              <progress
                value={rank.progress ?? 0}
                max={1}
                aria-label={`Progress to ${rank.next_name}`}
                className="mt-1.5 h-2 w-full overflow-hidden rounded-full [&::-moz-progress-bar]:bg-primary [&::-webkit-progress-bar]:rounded-full [&::-webkit-progress-bar]:bg-muted [&::-webkit-progress-value]:rounded-full [&::-webkit-progress-value]:bg-primary"
              />
            </div>
          ) : rank?.current_name && !rank.next_name ? (
            <p className="mt-4 text-sm text-muted-foreground">
              Top rank reached.
              {rank.current_reward ? ` ${rank.current_reward}.` : ""}
            </p>
          ) : null}
        </>
      ) : (
        <p className="mt-2 text-sm text-muted-foreground">
          Nothing sold yet this month.
          {rank?.next_name && rank.next_threshold !== null
            ? ` ${formatCurrency(rank.next_threshold ?? 0)} reaches ${rank.next_name}.`
            : ""}
        </p>
      )}
    </section>
  );
}
