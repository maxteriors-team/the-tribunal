"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Calendar,
  Mail,
  MessageSquare,
  Phone,
  Sparkles,
  Tag,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  PageErrorState,
  PageLoadingState,
} from "@/components/ui/page-state";
import { opportunitiesApi } from "@/lib/api/opportunities";
import { queryKeys } from "@/lib/query-keys";
import { cn } from "@/lib/utils";
import { getApiErrorMessage } from "@/lib/utils/errors";
import type {
  CoachActionChannel,
  DealHealthStatus,
} from "@/types";

const HEALTH_STYLES: Record<
  DealHealthStatus,
  { label: string; badge: string; bar: string }
> = {
  healthy: {
    label: "Healthy",
    badge: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
    bar: "bg-green-500",
  },
  watch: {
    label: "Watch",
    badge: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200",
    bar: "bg-yellow-500",
  },
  at_risk: {
    label: "At Risk",
    badge: "bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200",
    bar: "bg-orange-500",
  },
  critical: {
    label: "Critical",
    badge: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
    bar: "bg-red-500",
  },
};

const CHANNEL_ICON: Record<CoachActionChannel, React.ReactNode> = {
  sms: <MessageSquare className="h-4 w-4" />,
  call: <Phone className="h-4 w-4" />,
  email: <Mail className="h-4 w-4" />,
  offer: <Tag className="h-4 w-4" />,
  task: <Calendar className="h-4 w-4" />,
};

interface DealCoachCardProps {
  workspaceId: string;
  opportunityId: string;
}

export function DealCoachCard({ workspaceId, opportunityId }: DealCoachCardProps) {
  const queryClient = useQueryClient();

  const {
    data: card,
    isPending,
    isError,
    refetch,
  } = useQuery({
    queryKey: queryKeys.opportunities.coach(workspaceId, opportunityId),
    queryFn: () => opportunitiesApi.coach(workspaceId, opportunityId),
    enabled: !!workspaceId && !!opportunityId,
  });

  const draftMutation = useMutation({
    mutationFn: () =>
      opportunitiesApi.draftCoachAction(workspaceId, opportunityId),
    onSuccess: (res) => {
      if (res.decision === "blocked") {
        toast.error("This action is blocked by your approval policy.");
        return;
      }
      toast.success(
        res.decision === "pending"
          ? "Drafted action queued for approval"
          : "Action approved automatically"
      );
      void queryClient.invalidateQueries({
        queryKey: queryKeys.pendingActions.root(),
      });
    },
    onError: (err: unknown) =>
      toast.error(getApiErrorMessage(err, "Failed to queue drafted action")),
  });

  if (isPending) {
    return (
      <Card>
        <CardContent className="py-4">
          <PageLoadingState message="Analyzing the deal…" />
        </CardContent>
      </Card>
    );
  }

  if (isError || !card) {
    return (
      <Card>
        <CardContent className="py-4">
          <PageErrorState
            message="Couldn't load the deal coach."
            onRetry={() => void refetch()}
          />
        </CardContent>
      </Card>
    );
  }

  const health = HEALTH_STYLES[card.deal_health];
  const nba = card.next_best_action;

  return (
    <Card data-slot="deal-coach-card">
      <CardHeader className="flex flex-row items-center justify-between pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <Sparkles className="h-4 w-4 text-primary" />
          AI Deal Coach
        </CardTitle>
        <Badge className={cn("font-medium", health.badge)}>{health.label}</Badge>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Health bar */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">Deal health</span>
            <span className="font-medium">{card.health_score}/100</span>
          </div>
          <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
            <div
              className={cn("h-full rounded-full transition-all", health.bar)}
              style={{ width: `${card.health_score}%` }}
            />
          </div>
          <p className="text-sm text-muted-foreground">{card.health_summary}</p>
        </div>

        {/* Top risk */}
        <div className="flex items-start gap-2 rounded-lg border border-orange-200 bg-orange-50 p-3 dark:border-orange-900 dark:bg-orange-950/40">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-orange-600" />
          <div className="space-y-1">
            <p className="text-sm font-medium">Top risk</p>
            <p className="text-sm text-muted-foreground">{card.top_risk}</p>
          </div>
        </div>

        {/* Next best action */}
        <div className="space-y-2 rounded-lg border p-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              {CHANNEL_ICON[nba.channel]}
              <p className="text-sm font-medium">{nba.title}</p>
            </div>
            <Badge variant="outline" className="text-xs">
              {nba.timing}
            </Badge>
          </div>
          <p className="text-sm text-muted-foreground">{nba.rationale}</p>

          {/* Drafted action preview */}
          <div className="rounded-md bg-muted/60 p-2.5 text-sm">
            <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Drafted {card.drafted_action.channel}
            </p>
            <p className="whitespace-pre-wrap">{card.drafted_action.body}</p>
          </div>

          <Button
            size="sm"
            className="w-full"
            onClick={() => draftMutation.mutate()}
            disabled={draftMutation.isPending}
          >
            {draftMutation.isPending
              ? "Queuing…"
              : "Send to approval queue"}
          </Button>
        </div>

        {/* Signals footer */}
        <SignalRow card={card} />
      </CardContent>
    </Card>
  );
}

function SignalRow({
  card,
}: {
  card: { signals: { sentiment_trend: string }; generated_by: string };
}) {
  const trend = card.signals.sentiment_trend;
  return (
    <div className="flex items-center justify-between border-t pt-3 text-xs text-muted-foreground">
      <span className="flex items-center gap-1">
        {trend === "improving" ? (
          <TrendingUp className="h-3.5 w-3.5 text-green-500" />
        ) : trend === "declining" ? (
          <TrendingDown className="h-3.5 w-3.5 text-red-500" />
        ) : null}
        Sentiment: {trend}
      </span>
      <span>
        {card.generated_by === "llm" ? "AI synthesized" : "Rule-based"}
      </span>
    </div>
  );
}
