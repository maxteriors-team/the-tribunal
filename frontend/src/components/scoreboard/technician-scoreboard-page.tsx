"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, LockKeyhole, Trophy, Zap } from "lucide-react";
import Link from "next/link";
import { useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { PageEmptyState, PageErrorState, PageLoadingState } from "@/components/ui/page-state";
import { Progress } from "@/components/ui/progress";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { useCapabilities } from "@/hooks/useCapabilities";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import {
  technicianScoreboardApi,
  type TechnicianScoreboard,
  type TechnicianScoreboardDetail,
} from "@/lib/api/technician-scoreboard";
import { queryKeys } from "@/lib/query-keys";
import { POLL_30S } from "@/lib/query-options";
import { cn } from "@/lib/utils";
import { formatNumber } from "@/lib/utils/number";

function formatMonth(isoDate: string): string {
  const [year, month, day] = isoDate.split("-").map(Number);
  return new Date(year, month - 1, day).toLocaleDateString(undefined, {
    month: "long",
    year: "numeric",
  });
}

function DetailBreakdown({ detail }: { detail: TechnicianScoreboardDetail }) {
  const categories = [
    { label: "Attendance days", count: detail.attendance_days, xp: detail.attendance_xp },
    { label: "Completed jobs", count: detail.completed_jobs, xp: detail.job_xp },
    { label: "Approved upsells", count: detail.approved_upsells, xp: detail.upsell_xp },
  ];

  return (
    <dl className="divide-y border-y">
      {categories.map((category) => (
        <div
          key={category.label}
          className="grid min-h-14 grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-3 py-3 text-sm"
        >
          <dt className="min-w-0 font-medium">{category.label}</dt>
          <dd className="tabular-nums text-muted-foreground">
            {formatNumber(category.count)} {category.count === 1 ? "source" : "sources"}
          </dd>
          <dd className="min-w-16 text-end font-semibold tabular-nums">
            {formatNumber(category.xp)} XP
          </dd>
        </div>
      ))}
    </dl>
  );
}

function PersonalProgress({ detail }: { detail: TechnicianScoreboardDetail }) {
  const isTopLevel = detail.next_level_number === null;
  const progressValue = Math.round(detail.level_progress * 100);

  return (
    <section aria-labelledby="your-lighting-level" className="border bg-card">
      <div className="grid gap-6 p-5 md:grid-cols-[minmax(0,1.3fr)_minmax(18rem,0.7fr)] md:p-6">
        <div className="min-w-0">
          <p className="text-sm font-medium text-muted-foreground">Your lifetime level</p>
          <div className="mt-2 flex items-start gap-4">
            <div
              aria-hidden="true"
              className="flex size-14 shrink-0 items-center justify-center border border-foreground bg-primary text-xl font-black text-primary-foreground"
            >
              {detail.level_number}
            </div>
            <div className="min-w-0">
              <h2 id="your-lighting-level" className="text-xl font-semibold tracking-tight">
                {detail.level_title}
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">
                {formatNumber(detail.lifetime_xp)} lifetime XP
              </p>
            </div>
          </div>

          <div className="mt-6">
            <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
              <span className="font-medium">
                {isTopLevel
                  ? "All ten levels complete"
                  : `${formatNumber(detail.xp_to_next_level ?? 0)} XP to ${detail.next_level_title}`}
              </span>
              <span className="tabular-nums text-muted-foreground">
                {isTopLevel
                  ? `${formatNumber(detail.lifetime_xp)} XP and counting`
                  : `${formatNumber(detail.xp_into_level)} / ${formatNumber(
                      (detail.next_level_threshold ?? 0) - detail.current_level_threshold,
                    )} XP`}
              </span>
            </div>
            <Progress
              value={progressValue}
              max={100}
              aria-label={
                isTopLevel
                  ? "Top Lighting League level complete"
                  : `Progress to ${detail.next_level_title}`
              }
              className="mt-2 h-2 rounded-none [&>div]:bg-foreground"
            />
          </div>
        </div>

        <div>
          <div className="mb-3 flex items-baseline justify-between gap-3">
            <h3 className="font-semibold">This month</h3>
            <span className="font-semibold tabular-nums">{formatNumber(detail.monthly_xp)} XP</span>
          </div>
          <DetailBreakdown detail={detail} />
        </div>
      </div>
    </section>
  );
}

function LevelPath({
  levels,
  currentLevel,
}: {
  levels: TechnicianScoreboard["levels"];
  currentLevel?: number;
}) {
  return (
    <section aria-labelledby="level-path-heading">
      <div className="mb-4">
        <h2 id="level-path-heading" className="text-lg font-semibold">
          Lighting level path
        </h2>
        <p className="text-sm text-muted-foreground">
          Lifetime XP stays with you. It never resets at month end.
        </p>
      </div>
      <ol
        aria-label="Lighting League levels"
        className="relative grid gap-0 border-s border-border ps-5 lg:grid-cols-10 lg:border-s-0 lg:border-t lg:ps-0 lg:pt-5"
      >
        {levels.map((level) => {
          const completed = currentLevel !== undefined && level.number < currentLevel;
          const current = level.number === currentLevel;
          const future = currentLevel !== undefined && level.number > currentLevel;
          const state = completed ? "Completed" : current ? "Current" : future ? "Future" : null;
          return (
            <li
              key={level.number}
              className="relative min-w-0 border-b py-4 ps-4 last:border-b-0 lg:border-b-0 lg:px-2 lg:py-0 lg:text-center"
            >
              <span
                aria-hidden="true"
                className={cn(
                  "absolute -start-[1.7rem] top-4 flex size-6 items-center justify-center border bg-background text-[11px] font-bold lg:-top-8 lg:start-1/2 lg:-translate-x-1/2",
                  completed && "border-foreground bg-foreground text-background",
                  current && "border-foreground bg-primary text-primary-foreground",
                )}
              >
                {completed ? (
                  <Check className="size-3.5" strokeWidth={3} />
                ) : future ? (
                  <LockKeyhole className="size-3" />
                ) : (
                  level.number
                )}
              </span>
              <p className="text-xs font-medium text-muted-foreground">
                Level {level.number}
                {state ? ` · ${state}` : ""}
              </p>
              <p className="mt-0.5 text-sm font-semibold leading-tight">{level.title}</p>
              <p className="mt-1 text-xs tabular-nums text-muted-foreground">
                {formatNumber(level.lifetime_xp)} XP
              </p>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function LevelUpBanner({
  detail,
  pending,
  failed,
  onDismiss,
}: {
  detail: TechnicianScoreboardDetail;
  pending: boolean;
  failed: boolean;
  onDismiss: () => void;
}) {
  return (
    <section
      aria-labelledby="level-up-heading"
      className="relative overflow-hidden border border-primary bg-card p-5 ps-7"
    >
      <span aria-hidden="true" className="absolute inset-y-0 start-0 w-2 bg-primary" />
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <h2 id="level-up-heading" className="font-semibold">
            Level {detail.level_number} unlocked: {detail.level_title}
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Your lifetime XP powered up a new lighting level.
          </p>
          {pending ? (
            <p role="status" className="mt-2 text-sm text-muted-foreground">
              Dismissing level-up message.
            </p>
          ) : failed ? (
            <p role="alert" className="mt-2 text-sm font-medium text-destructive">
              We could not dismiss this yet. Your level and XP are unchanged.
            </p>
          ) : null}
        </div>
        <Button
          type="button"
          variant="outline"
          className="min-h-11 shrink-0 hover:scale-100 active:scale-100"
          disabled={pending}
          aria-label={
            pending
              ? "Dismissing level-up message"
              : failed
                ? "Try dismissing level-up message again"
                : "Dismiss level-up message"
          }
          onClick={onDismiss}
        >
          {pending ? "Dismissing…" : failed ? "Try dismissing again" : "Dismiss"}
        </Button>
      </div>
    </section>
  );
}

function Standings({
  data,
  canViewDetails,
  onSelect,
}: {
  data: TechnicianScoreboard;
  canViewDetails: boolean;
  onSelect: (technicianId: string, trigger: HTMLButtonElement) => void;
}) {
  const month = formatMonth(data.period.start_date);
  const rankCounts = new Map<number, number>();
  for (const row of data.standings) {
    if (row.rank !== null) rankCounts.set(row.rank, (rankCounts.get(row.rank) ?? 0) + 1);
  }
  const noMonthlyXp = data.standings.every((row) => row.monthly_xp === 0);

  return (
    <section aria-labelledby="standings-heading" className="border bg-card">
      <div className="border-b p-5 md:p-6">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 id="standings-heading" className="text-lg font-semibold">
              {month} standings
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Monthly XP resets on the first day in {data.period.timezone}.
            </p>
          </div>
          {canViewDetails ? (
            <p className="text-xs text-muted-foreground">
              Select a technician for private details.
            </p>
          ) : null}
        </div>
        {noMonthlyXp ? (
          <p className="mt-4 border-s-2 border-primary ps-3 text-sm">
            No XP earned this month yet. The active roster stays visible below.
          </p>
        ) : null}
      </div>

      <div className="hidden grid-cols-[7rem_minmax(0,1fr)_8rem_11rem] gap-4 border-b px-5 py-2 text-xs font-medium text-muted-foreground md:grid md:px-6">
        <span>Rank</span>
        <span>Technician</span>
        <span className="text-end">Monthly XP</span>
        <span>Lighting level</span>
      </div>
      <ol aria-label={`${month} technician standings`}>
        {data.standings.map((row) => {
          const tied = row.rank !== null && (rankCounts.get(row.rank) ?? 0) > 1;
          const rankLabel =
            row.rank === null ? "Not ranked" : tied ? `Tied #${row.rank}` : `#${row.rank}`;
          const content = (
            <>
              <span className="font-semibold tabular-nums">{rankLabel}</span>
              <span className="min-w-0 break-words">
                <span className="font-medium">{row.name}</span>
                {row.is_viewer ? (
                  <span className="ms-2 border border-foreground px-1.5 py-0.5 text-[11px] font-semibold">
                    You
                  </span>
                ) : null}
              </span>
              <span className="text-end font-semibold tabular-nums">
                {formatNumber(row.monthly_xp)} XP
              </span>
              <span className="text-sm text-muted-foreground">
                Level {row.level_number}: {row.level_title}
              </span>
            </>
          );
          const rowClass = cn(
            "relative grid min-h-16 w-full grid-cols-[6rem_minmax(0,1fr)] items-center gap-x-3 gap-y-1 border-b px-5 py-3 text-start last:border-b-0 md:grid-cols-[7rem_minmax(0,1fr)_8rem_11rem] md:gap-4 md:px-6",
            row.is_viewer && "border-s-4 border-s-primary ps-4 md:ps-5",
          );

          return (
            <li key={row.technician_id}>
              {canViewDetails ? (
                <button
                  type="button"
                  aria-label={`View private Lighting League details for ${row.name}`}
                  aria-haspopup="dialog"
                  className={cn(
                    rowClass,
                    "transition-colors hover:bg-muted/60 active:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
                  )}
                  onClick={(event) => onSelect(row.technician_id, event.currentTarget)}
                >
                  {content}
                </button>
              ) : (
                <div className={rowClass}>{content}</div>
              )}
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function HowXpWorks({ data }: { data: TechnicianScoreboard }) {
  const rules = data.rules;
  return (
    <section aria-labelledby="xp-rules-heading" className="border-t pt-6">
      <div className="grid gap-5 lg:grid-cols-[minmax(14rem,0.65fr)_minmax(0,1.35fr)]">
        <div>
          <h2 id="xp-rules-heading" className="text-lg font-semibold">
            How XP works
          </h2>
          <p className="mt-1 max-w-md text-sm text-muted-foreground">
            Positive work earns recognition. Lighting League does not set pay, prizes, discipline,
            or performance reviews.
          </p>
        </div>
        <ul className="divide-y border-y text-sm">
          <li className="grid gap-1 py-3 sm:grid-cols-[8rem_1fr] sm:gap-4">
            <span className="font-semibold tabular-nums">{rules.attendance_day_xp} XP</span>
            <span className="text-muted-foreground">
              One completed, non-void clocked day. Multiple entries on one day still count once.
            </span>
          </li>
          <li className="grid gap-1 py-3 sm:grid-cols-[8rem_1fr] sm:gap-4">
            <span className="font-semibold tabular-nums">{rules.completed_job_xp} XP</span>
            <span className="text-muted-foreground">
              A job&apos;s first completion. Every technician assigned at that moment receives full
              credit.
            </span>
          </li>
          <li className="grid gap-1 py-3 sm:grid-cols-[8rem_1fr] sm:gap-4">
            <span className="font-semibold tabular-nums">
              {rules.upsell_base_xp}–{rules.upsell_max_xp} XP
            </span>
            <span className="text-muted-foreground">
              An approved on-site upsell: {rules.upsell_base_xp} XP plus 1 XP per $
              {rules.upsell_value_divisor}, capped at {rules.upsell_max_xp} XP.
            </span>
          </li>
          <li className="grid gap-1 py-3 sm:grid-cols-[8rem_1fr] sm:gap-4">
            <span className="font-semibold">Two clocks</span>
            <span className="text-muted-foreground">
              Standings reset monthly. Lifetime XP and lighting levels never reset.
            </span>
          </li>
        </ul>
      </div>
    </section>
  );
}

function TechnicianDetailSheet({
  open,
  onOpenChange,
  returnFocus,
  detail,
  loading,
  failed,
  onRetry,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  returnFocus: () => void;
  detail?: TechnicianScoreboardDetail;
  loading: boolean;
  failed: boolean;
  onRetry: () => void;
}) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          returnFocus();
        }}
        className="w-full overflow-y-auto motion-reduce:transition-none sm:max-w-md"
      >
        <SheetHeader className="border-b pe-14">
          <SheetTitle>{detail?.name ?? "Technician details"}</SheetTitle>
          <SheetDescription>
            Private lifetime progress and this month&apos;s contribution sources.
          </SheetDescription>
        </SheetHeader>
        <div className="p-4">
          {failed ? (
            <PageErrorState
              className="min-h-64 px-2"
              title="Details unavailable"
              message="We could not load this private breakdown. Try again."
              onRetry={onRetry}
            />
          ) : loading || !detail ? (
            <PageLoadingState className="min-h-64 px-2" message="Loading private details…" />
          ) : (
            <div className="space-y-6">
              <div className="border-s-4 border-primary ps-4">
                <p className="text-sm text-muted-foreground">Lifetime level</p>
                <p className="mt-1 text-lg font-semibold">
                  Level {detail.level_number}: {detail.level_title}
                </p>
                <p className="mt-1 text-sm tabular-nums text-muted-foreground">
                  {formatNumber(detail.lifetime_xp)} lifetime XP
                </p>
              </div>
              <div>
                <div className="mb-3 flex items-baseline justify-between gap-3">
                  <h3 className="font-semibold">This month</h3>
                  <span className="font-semibold tabular-nums">
                    {formatNumber(detail.monthly_xp)} XP
                  </span>
                </div>
                <DetailBreakdown detail={detail} />
              </div>
              <p className="text-sm text-muted-foreground">
                These details are visible only to this technician and office staff who manage jobs.
              </p>
            </div>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

export function TechnicianScoreboardPage() {
  const workspaceId = useWorkspaceId();
  const { can } = useCapabilities();
  const canReadJobs = can("jobs:read");
  const canViewDetails = can("jobs:write");
  const queryClient = useQueryClient();
  const [selectedTechnicianId, setSelectedTechnicianId] = useState<string | null>(null);
  const detailTriggerRef = useRef<HTMLButtonElement>(null);

  const scoreboardQuery = useQuery({
    queryKey: queryKeys.technicianScoreboard.all(workspaceId ?? ""),
    queryFn: () => {
      if (!workspaceId) throw new Error("No workspace");
      return technicianScoreboardApi.get(workspaceId);
    },
    enabled: !!workspaceId && canReadJobs,
    ...POLL_30S,
    placeholderData: (previous) => previous,
  });

  const detailQuery = useQuery({
    queryKey: queryKeys.technicianScoreboard.detail(workspaceId ?? "", selectedTechnicianId ?? ""),
    queryFn: () => {
      if (!workspaceId || !selectedTechnicianId) throw new Error("No technician selected");
      return technicianScoreboardApi.detail(workspaceId, selectedTechnicianId);
    },
    enabled: !!workspaceId && !!selectedTechnicianId && canViewDetails,
  });

  const acknowledgeMutation = useMutation({
    mutationFn: (level: number) => {
      if (!workspaceId) throw new Error("No workspace");
      return technicianScoreboardApi.acknowledgeLevel(workspaceId, level);
    },
    onSuccess: (response) => {
      if (!workspaceId) return;
      queryClient.setQueryData<TechnicianScoreboard>(
        queryKeys.technicianScoreboard.all(workspaceId),
        (current) => (current ? { ...current, viewer_level_seen: response.level_seen } : current),
      );
    },
  });

  if (!canReadJobs) {
    return (
      <PageErrorState title="Access denied" message="Your role cannot view Lighting League." />
    );
  }

  const data = scoreboardQuery.data;
  const viewerLevelUp =
    data?.viewer_detail &&
    data.viewer_level_seen !== null &&
    data.viewer_detail.level_number > data.viewer_level_seen
      ? data.viewer_detail
      : null;

  return (
    <div className="h-full overflow-y-auto">
      <main className="mx-auto w-full max-w-7xl space-y-6 p-4 pb-24 sm:p-6 lg:space-y-8">
        <header>
          <div className="flex items-center gap-3">
            <Zap aria-hidden="true" className="size-6 fill-primary text-primary" />
            <h1 className="text-2xl font-semibold tracking-tight">Lighting League</h1>
          </div>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            Earn XP from showing up, completing jobs, and approved upsells.
          </p>
        </header>

        {scoreboardQuery.isError && !data ? (
          <PageErrorState
            title="Lighting League unavailable"
            message="We could not load the standings. Check your connection and try again."
            onRetry={() => void scoreboardQuery.refetch()}
          />
        ) : scoreboardQuery.isPending || !data ? (
          <PageLoadingState message="Loading Lighting League…" />
        ) : data.standings.length === 0 ? (
          <PageEmptyState
            icon={<Trophy aria-hidden="true" className="size-8" />}
            title="No active technicians"
            description={
              canViewDetails
                ? "Add or reactivate a technician in Team settings to start Lighting League."
                : "Lighting League will appear when your workspace has active technicians."
            }
            action={
              canViewDetails ? (
                <Button
                  asChild
                  variant="outline"
                  className="min-h-11 hover:scale-100 active:scale-100"
                >
                  <Link href="/settings?tab=team">Open Team settings</Link>
                </Button>
              ) : undefined
            }
          />
        ) : (
          <>
            {scoreboardQuery.isError ? (
              <div
                role="status"
                className="flex flex-col gap-3 border-s-4 border-primary bg-card p-4 sm:flex-row sm:items-center sm:justify-between"
              >
                <p className="text-sm">
                  These standings may be out of date. The last loaded results remain visible.
                </p>
                <Button
                  type="button"
                  variant="outline"
                  className="min-h-11 shrink-0 hover:scale-100 active:scale-100"
                  onClick={() => void scoreboardQuery.refetch()}
                >
                  Refresh standings
                </Button>
              </div>
            ) : null}

            {viewerLevelUp ? (
              <LevelUpBanner
                detail={viewerLevelUp}
                pending={acknowledgeMutation.isPending}
                failed={acknowledgeMutation.isError}
                onDismiss={() => acknowledgeMutation.mutate(viewerLevelUp.level_number)}
              />
            ) : null}
            <span className="sr-only" aria-live="polite">
              {acknowledgeMutation.isSuccess ? "Level-up message dismissed." : ""}
            </span>

            {data.viewer_detail ? <PersonalProgress detail={data.viewer_detail} /> : null}
            <LevelPath levels={data.levels} currentLevel={data.viewer_detail?.level_number} />
            <Standings
              data={data}
              canViewDetails={canViewDetails}
              onSelect={(technicianId, trigger) => {
                detailTriggerRef.current = trigger;
                setSelectedTechnicianId(technicianId);
              }}
            />
            <HowXpWorks data={data} />
          </>
        )}
      </main>

      <TechnicianDetailSheet
        open={selectedTechnicianId !== null}
        onOpenChange={(open) => {
          if (!open) setSelectedTechnicianId(null);
        }}
        returnFocus={() => detailTriggerRef.current?.focus()}
        detail={detailQuery.data}
        loading={detailQuery.isPending}
        failed={detailQuery.isError}
        onRetry={() => void detailQuery.refetch()}
      />
    </div>
  );
}
