"use client";

/* eslint-disable jsx-a11y/no-noninteractive-tabindex -- The named scorecard scroll region must accept keyboard focus. */

import { useQuery } from "@tanstack/react-query";
import {
  PhoneCall,
  PhoneMissed,
  CalendarCheck,
  DollarSign,
  Moon,
  Timer,
  MessageSquareReply,
  ListChecks,
  UserPlus,
  Users,
} from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PageEmptyState, PageErrorState, PageLoadingState } from "@/components/ui/page-state";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useCapabilities } from "@/hooks/useCapabilities";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import {
  scorecardApi,
  type ReceptionistScorecard,
  type TechnicianActivityScorecardRow,
} from "@/lib/api/scorecard";
import { queryKeys } from "@/lib/query-keys";
import { REALTIME } from "@/lib/query-options";
import { formatCurrency, formatNumber } from "@/lib/utils/number";

const RANGE_PRESETS = [
  { value: "7", label: "7 days" },
  { value: "30", label: "30 days" },
  { value: "90", label: "90 days" },
] as const;

type RangePreset = (typeof RANGE_PRESETS)[number]["value"];

function toIsoDate(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function rangeFromPreset(days: number): { start_date: string; end_date: string } {
  const end = new Date();
  const start = new Date();
  start.setDate(start.getDate() - (days - 1));
  return { start_date: toIsoDate(start), end_date: toIsoDate(end) };
}

function formatRate(rate: number | null): string {
  return rate === null ? "—" : `${rate.toFixed(1)}%`;
}

function formatSeconds(seconds: number | null): string {
  if (seconds === null) return "—";
  const mins = Math.floor(seconds / 60);
  const secs = Math.round(seconds % 60);
  return mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;
}

function formatHours(seconds: number): string {
  return `${(seconds / 3600).toFixed(1)}h`;
}

/** Render an API date (YYYY-MM-DD) without letting the local timezone shift it.
 *
 * `new Date("2026-01-05")` parses as UTC midnight, which renders as Jan 4 for
 * anyone west of UTC — the exact off-by-one-day the server-side local bucketing
 * avoids. Formatting from the parts keeps the label matching its bucket.
 */
function formatDayLabel(isoDate: string): string {
  const [year, month, day] = isoDate.split("-").map(Number);
  return new Date(year, month - 1, day).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}

export function ScorecardPage() {
  const workspaceId = useWorkspaceId();
  const { can } = useCapabilities();
  const canViewReports = can("reports:view");
  const [preset, setPreset] = useState<RangePreset>("30");
  const [view, setView] = useState<"receptionist" | "technicians">("receptionist");

  const range = useMemo(() => rangeFromPreset(Number(preset)), [preset]);

  const receptionistQuery = useQuery({
    queryKey: queryKeys.scorecard.range(workspaceId ?? "", range),
    queryFn: () => {
      if (!workspaceId) throw new Error("No workspace");
      return scorecardApi.get(workspaceId, range);
    },
    enabled: !!workspaceId && canViewReports && view === "receptionist",
    ...REALTIME,
    placeholderData: (prev) => prev,
  });
  const technicianQuery = useQuery({
    queryKey: queryKeys.scorecard.technicians(workspaceId ?? "", range),
    queryFn: () => {
      if (!workspaceId) throw new Error("No workspace");
      return scorecardApi.getTechnicians(workspaceId, range);
    },
    enabled: !!workspaceId && canViewReports && view === "technicians",
    ...REALTIME,
    placeholderData: (prev) => prev,
  });

  const heading = view === "receptionist" ? "Receptionist Scorecard" : "Technician Scorecard";

  if (!canViewReports) {
    return <PageErrorState title="Access denied" message="Your role cannot view scorecards." />;
  }

  return (
    <div
      tabIndex={0}
      role="region"
      aria-labelledby="scorecard-heading"
      className="h-full overflow-y-auto focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
    >
      <div className="space-y-6 p-4 sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 id="scorecard-heading" className="text-2xl font-semibold tracking-tight">
              {heading}
            </h1>
            <p className="text-sm text-muted-foreground">
              {view === "receptionist"
                ? "How your AI receptionist captured, recovered, and booked demand."
                : "Recorded field activity by technician—without rankings or quality judgments."}
            </p>
          </div>
          <div
            role="group"
            aria-label="Scorecard date range"
            className="inline-flex h-9 items-center justify-center rounded-lg bg-muted p-[3px]"
          >
            {RANGE_PRESETS.map((rangePreset) => (
              <Button
                key={rangePreset.value}
                type="button"
                size="sm"
                variant={preset === rangePreset.value ? "secondary" : "ghost"}
                aria-pressed={preset === rangePreset.value}
                onClick={() => setPreset(rangePreset.value)}
                className="h-[calc(100%-1px)] px-2 py-1 text-sm shadow-none"
              >
                {rangePreset.label}
              </Button>
            ))}
          </div>
        </div>

        <Tabs value={view} onValueChange={(value) => setView(value as typeof view)}>
          <TabsList aria-label="Scorecard type">
            <TabsTrigger value="receptionist">AI receptionist</TabsTrigger>
            <TabsTrigger value="technicians">Technicians</TabsTrigger>
          </TabsList>
          <TabsContent value="receptionist" className="mt-6">
            {receptionistQuery.isError && !receptionistQuery.data ? (
              <PageErrorState
                message="We couldn't load the receptionist scorecard. Please try again."
                onRetry={() => receptionistQuery.refetch()}
              />
            ) : receptionistQuery.isPending || !receptionistQuery.data ? (
              <PageLoadingState message="Loading scorecard…" />
            ) : (
              <ScorecardBody data={receptionistQuery.data} />
            )}
          </TabsContent>
          <TabsContent value="technicians" className="mt-6">
            {technicianQuery.isError && !technicianQuery.data ? (
              <PageErrorState
                message="We couldn't load technician activity. Please try again."
                onRetry={() => technicianQuery.refetch()}
              />
            ) : technicianQuery.isPending || !technicianQuery.data ? (
              <PageLoadingState message="Loading technician activity…" />
            ) : (
              <TechnicianScorecardBody data={technicianQuery.data} />
            )}
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}

function TechnicianScorecardBody({ data }: { data: TechnicianActivityScorecardRow[] }) {
  if (data.length === 0) {
    return (
      <PageEmptyState
        icon={<Users className="size-8" />}
        title="No technicians yet"
        description="Add a technician to the field-service roster to see recorded activity here."
      />
    );
  }

  return (
    <div className="space-y-4">
      <div className="rounded-lg border bg-muted/30 p-4 text-sm">
        <p className="font-medium">Activity context—not an employee rating</p>
        <p className="mt-1 text-muted-foreground">
          These totals show assignments and recorded time only. They do not measure work quality,
          pay, productivity, or customer satisfaction.
        </p>
      </div>
      <div className="grid gap-4 xl:grid-cols-2" role="list" aria-label="Technician activity">
        {data.map((technician) => {
          const metrics = [
            { label: "Assigned jobs", value: formatNumber(technician.assigned_jobs) },
            {
              label: "Completed job logs",
              value: formatNumber(technician.completed_job_time_entries),
            },
            { label: "Job time", value: formatHours(technician.job_logged_seconds) },
            {
              label: "Attendance time",
              value: formatHours(technician.attendance_worked_seconds),
            },
            { label: "Paused time", value: formatHours(technician.attendance_paused_seconds) },
          ];
          return (
            <Card key={technician.id} role="listitem">
              <CardHeader className="flex flex-row items-center justify-between gap-3 pb-3">
                <CardTitle className="min-w-0 truncate text-base">{technician.name}</CardTitle>
                <Badge variant={technician.active ? "secondary" : "outline"}>
                  {technician.active ? "Active" : "Inactive"}
                </Badge>
              </CardHeader>
              <CardContent className="grid grid-cols-2 gap-4 sm:grid-cols-5">
                {metrics.map((metric) => (
                  <div key={metric.label} className="min-w-0">
                    <p className="text-xs text-muted-foreground">{metric.label}</p>
                    <p className="mt-1 text-lg font-semibold tabular-nums">{metric.value}</p>
                  </div>
                ))}
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
}

function ScorecardBody({ data }: { data: ReceptionistScorecard }) {
  const hasActivity =
    data.calls_total > 0 ||
    data.new_leads_total > 0 ||
    data.appointments_booked > 0 ||
    data.revenue_booked > 0 ||
    data.deposits_booked > 0;
  if (!hasActivity) {
    return (
      <PageEmptyState
        icon={<PhoneCall className="size-8" />}
        title="No receptionist calls yet"
        description="Connect a phone number and turn on the AI receptionist to start scoring calls, recoveries, and booked revenue."
        action={
          <Button asChild>
            <Link href="/phone-numbers">Connect a phone number</Link>
          </Button>
        }
      />
    );
  }

  const metrics = [
    {
      key: "new-leads",
      label: "New leads",
      icon: UserPlus,
      value: formatNumber(data.new_leads_total),
      sub:
        data.avg_new_leads_per_day === null
          ? "in selected range"
          : `${formatNumber(data.avg_new_leads_per_day)}/day average`,
      tone: "text-foreground",
    },
    {
      key: "answered",
      label: "Calls answered",
      icon: PhoneCall,
      value: `${formatNumber(data.calls_answered)} / ${formatNumber(data.calls_total)}`,
      sub: `${formatRate(data.answer_rate)} answer rate`,
      tone: "text-success",
    },
    {
      key: "missed",
      label: "Missed calls",
      icon: PhoneMissed,
      value: formatNumber(data.missed_calls),
      sub: `${formatNumber(data.missed_calls_textback_sent)} text-backs sent`,
      tone: "text-destructive",
    },
    {
      key: "recovered",
      label: "Missed recovered",
      icon: MessageSquareReply,
      value: formatNumber(data.missed_calls_recovered),
      sub: `${formatRate(data.recovery_rate)} recovery rate`,
      tone: "text-info",
    },
    {
      key: "appointments",
      label: "Appointments booked",
      icon: CalendarCheck,
      value: formatNumber(data.appointments_booked),
      sub: "in selected range",
      tone: "text-foreground",
    },
    {
      key: "revenue",
      label: "Revenue booked",
      icon: DollarSign,
      value: formatCurrency(data.revenue_booked, data.currency),
      sub: `${formatCurrency(data.deposits_booked, data.currency)} deposits collected`,
      tone: "text-success",
    },
    {
      key: "afterhours",
      label: "After-hours coverage",
      icon: Moon,
      value: formatRate(data.after_hours_coverage_rate),
      sub: `${formatNumber(data.after_hours_answered)} / ${formatNumber(data.after_hours_calls)} answered`,
      tone: "text-info",
    },
    {
      key: "handle",
      label: "Avg handle time",
      icon: Timer,
      value: formatSeconds(data.avg_handle_time_seconds),
      sub: "per answered call",
      tone: "text-foreground",
    },
  ];

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {metrics.map((m) => (
          <Card key={m.key}>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">{m.label}</CardTitle>
              <m.icon className="size-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className={`text-2xl font-bold ${m.tone}`}>{m.value}</div>
              <p className="text-xs text-muted-foreground">{m.sub}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      <NewLeadsByDayCard data={data} />

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <ListChecks className="size-4 text-muted-foreground" />
            Top call reasons
          </CardTitle>
        </CardHeader>
        <CardContent>
          {data.top_call_reasons.length === 0 ? (
            <PageEmptyState
              title="No call reasons yet"
              description="Once calls are analyzed, the most common reasons callers reach out will appear here."
            />
          ) : (
            <ul className="divide-y">
              {data.top_call_reasons.map((reason) => (
                <li key={reason.reason} className="flex items-center justify-between py-2 text-sm">
                  <span className="capitalize">{reason.reason}</span>
                  <span className="font-semibold tabular-nums">{formatNumber(reason.count)}</span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

/** Daily new-lead intake as a scaled bar series.
 *
 * Deliberately hand-rolled: the app ships no charting library, and a bar
 * series scaled against the range max needs no axis maths to stay readable.
 */
function NewLeadsByDayCard({ data }: { data: ReceptionistScorecard }) {
  const days = data.new_leads_by_day;
  const peak = days.reduce((max, d) => Math.max(max, d.count), 0);

  // Long ranges (90 days) can't show a label per bar without collapsing into
  // noise, so thin them to roughly six evenly spaced ticks.
  const labelStep = Math.max(1, Math.ceil(days.length / 6));

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <UserPlus className="size-4 text-muted-foreground" />
          New leads per day
        </CardTitle>
      </CardHeader>
      <CardContent>
        {days.length === 0 || peak === 0 ? (
          <PageEmptyState
            title="No new leads in this range"
            description="New contacts are counted on the day they're created. Capture a lead through a form, call, or import to see the daily trend."
          />
        ) : (
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">
              <span className="font-semibold text-foreground">
                {formatNumber(data.new_leads_total)}
              </span>{" "}
              new {data.new_leads_total === 1 ? "lead" : "leads"}
              {data.avg_new_leads_per_day === null
                ? null
                : ` · ${formatNumber(data.avg_new_leads_per_day)}/day average`}
              {` · peak ${formatNumber(peak)}`}
            </p>

            <div
              className="flex h-40 items-end gap-px"
              role="img"
              aria-label={`New leads per day from ${data.start_date} to ${data.end_date}. ${formatNumber(data.new_leads_total)} total, peak ${formatNumber(peak)} in one day.`}
            >
              {days.map((day) => (
                <div
                  key={day.date}
                  className="flex h-full flex-1 items-end"
                  title={`${formatDayLabel(day.date)}: ${formatNumber(day.count)} ${day.count === 1 ? "lead" : "leads"}`}
                >
                  <div
                    className={
                      day.count === 0
                        ? "w-full rounded-sm bg-muted"
                        : "w-full rounded-sm bg-primary"
                    }
                    // A zero day still renders a hairline track so the timeline
                    // reads as continuous instead of looking like missing data.
                    style={{
                      height: day.count === 0 ? "2px" : `${(day.count / peak) * 100}%`,
                    }}
                  />
                </div>
              ))}
            </div>

            <div className="flex justify-between text-xs text-muted-foreground">
              {days
                .filter((_, i) => i % labelStep === 0)
                .map((day) => (
                  <span key={day.date}>{formatDayLabel(day.date)}</span>
                ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
