"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Bell,
  ClipboardCheck,
  Megaphone,
  Radar,
  Sparkles,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  PageEmptyState,
  PageErrorState,
  PageLoadingState,
} from "@/components/ui/page-state";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { dashboardApi, type TodayQueueKind } from "@/lib/api/dashboard";
import { queryKeys } from "@/lib/query-keys";
import { POLL_60S } from "@/lib/query-options";

const KIND_ICONS: Record<TodayQueueKind, LucideIcon> = {
  approvals: ClipboardCheck,
  hot_nudges: Bell,
  prospect_batch: Radar,
  draft_campaign: Megaphone,
  setup_gap: Wrench,
};

const KIND_LABELS: Record<TodayQueueKind, string> = {
  approvals: "Approvals",
  hot_nudges: "Nudges",
  prospect_batch: "Fresh batch",
  draft_campaign: "Draft campaign",
  setup_gap: "Setup",
};

export function TodayPage() {
  const workspaceId = useWorkspaceId();

  const {
    data: queue,
    isPending,
    isError,
    refetch,
  } = useQuery({
    queryKey: queryKeys.dashboard.todayQueue(workspaceId ?? ""),
    queryFn: () => {
      if (!workspaceId) throw new Error("No workspace");
      return dashboardApi.getTodayQueue(workspaceId);
    },
    enabled: !!workspaceId,
    ...POLL_60S,
  });

  return (
    <div className="flex flex-col gap-6 p-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Today</h1>
          <p className="text-sm text-muted-foreground">
            Your ordered mission queue — work it top to bottom.
          </p>
        </div>
        <Button asChild>
          <Link href="/assistant?briefing=1">
            <Sparkles className="size-4" />
            Start my day
          </Link>
        </Button>
      </div>

      {isPending ? (
        <PageLoadingState message="Building today's queue…" />
      ) : isError ? (
        <PageErrorState
          message="We couldn't load today's queue. Please try again."
          onRetry={() => refetch()}
        />
      ) : queue.items.length === 0 ? (
        <PageEmptyState
          title="All clear"
          description="Nothing needs you right now. The machine keeps scraping overnight."
          action={
            <Button asChild variant="outline">
              <Link href="/assistant?briefing=1">Ask the assistant anyway</Link>
            </Button>
          }
        />
      ) : (
        <div className="flex flex-col gap-3">
          {queue.items.map((item, index) => {
            const Icon = KIND_ICONS[item.kind];
            return (
              <Card key={item.id}>
                <CardContent className="flex flex-wrap items-center gap-4 p-4">
                  <div className="flex size-9 shrink-0 items-center justify-center rounded-full bg-muted font-mono text-sm text-muted-foreground">
                    {index + 1}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <Icon className="size-4 shrink-0 text-muted-foreground" />
                      <span className="font-medium">{item.title}</span>
                      <Badge variant="secondary">{KIND_LABELS[item.kind]}</Badge>
                      {item.count > 1 ? (
                        <Badge variant="outline">{item.count}</Badge>
                      ) : null}
                    </div>
                    {item.body ? (
                      <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">
                        {item.body}
                      </p>
                    ) : null}
                  </div>
                  <Button asChild variant="outline" className="shrink-0">
                    <Link href={item.href}>{item.cta_label}</Link>
                  </Button>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
