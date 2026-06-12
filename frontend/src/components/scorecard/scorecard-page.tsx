"use client";

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
} from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  PageEmptyState,
  PageErrorState,
  PageLoadingState,
} from "@/components/ui/page-state";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { scorecardApi, type ReceptionistScorecard } from "@/lib/api/scorecard";
import { queryKeys } from "@/lib/query-keys";
import { POLL_60S } from "@/lib/query-options";
import { formatCurrency, formatNumber } from "@/lib/utils/number";

const RANGE_PRESETS = [
  { value: "7", label: "7 days" },
  { value: "30", label: "30 days" },
  { value: "90", label: "90 days" },
] as const;

type RangePreset = (typeof RANGE_PRESETS)[number]["value"];

function toIsoDate(date: Date): string {
  return date.toISOString().slice(0, 10);
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

export function ScorecardPage() {
  const workspaceId = useWorkspaceId();
  const [preset, setPreset] = useState<RangePreset>("30");

  const range = useMemo(() => rangeFromPreset(Number(preset)), [preset]);

  const { data, isPending, isError, refetch } = useQuery({
    queryKey: queryKeys.scorecard.range(workspaceId ?? "", range),
    queryFn: () => {
      if (!workspaceId) throw new Error("No workspace");
      return scorecardApi.get(workspaceId, range);
    },
    enabled: !!workspaceId,
    ...POLL_60S,
    placeholderData: (prev) => prev,
  });

  return (
    <div className="h-full overflow-y-auto">
      <div className="space-y-6 p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">
              Receptionist Scorecard
            </h1>
            <p className="text-sm text-muted-foreground">
              How your AI receptionist captured, recovered, and booked demand.
            </p>
          </div>
          <Tabs value={preset} onValueChange={(v) => setPreset(v as RangePreset)}>
            <TabsList>
              {RANGE_PRESETS.map((p) => (
                <TabsTrigger key={p.value} value={p.value}>
                  {p.label}
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
        </div>

        {isError && !data ? (
          <PageErrorState
            message="We couldn't load the scorecard. Please try again."
            onRetry={() => refetch()}
          />
        ) : isPending || !data ? (
          <PageLoadingState message="Loading scorecard…" />
        ) : (
          <ScorecardBody data={data} />
        )}
      </div>
    </div>
  );
}

function ScorecardBody({ data }: { data: ReceptionistScorecard }) {
  if (data.calls_total === 0) {
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
      sub: `${formatCurrency(data.deposits_booked, data.currency)} deposits won`,
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
              <CardTitle className="text-sm font-medium text-muted-foreground">
                {m.label}
              </CardTitle>
              <m.icon className="size-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className={`text-2xl font-bold ${m.tone}`}>{m.value}</div>
              <p className="text-xs text-muted-foreground">{m.sub}</p>
            </CardContent>
          </Card>
        ))}
      </div>

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
                <li
                  key={reason.reason}
                  className="flex items-center justify-between py-2 text-sm"
                >
                  <span className="capitalize">{reason.reason}</span>
                  <span className="font-semibold tabular-nums">
                    {formatNumber(reason.count)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
