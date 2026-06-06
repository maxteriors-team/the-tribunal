"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ShieldCheck } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  PageEmptyState,
  PageErrorState,
  PageLoadingState,
} from "@/components/ui/page-state";
import { opportunitiesApi } from "@/lib/api/opportunities";
import { queryKeys } from "@/lib/query-keys";
import { POLL_60S } from "@/lib/query-options";
import { cn } from "@/lib/utils";
import { formatCurrency } from "@/lib/utils/number";
import type { AtRiskDeal, DealHealthStatus } from "@/types";

const HEALTH_BADGE: Record<DealHealthStatus, string> = {
  healthy: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
  watch: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200",
  at_risk: "bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200",
  critical: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
};

interface AtRiskDealsListProps {
  workspaceId: string;
  limit?: number;
  onSelect?: (opportunityId: string) => void;
}

export function AtRiskDealsList({
  workspaceId,
  limit = 25,
  onSelect,
}: AtRiskDealsListProps) {
  const {
    data,
    isPending,
    isError,
    refetch,
  } = useQuery({
    queryKey: queryKeys.opportunities.atRisk(workspaceId, { limit }),
    queryFn: () => opportunitiesApi.listAtRisk(workspaceId, { limit }),
    enabled: !!workspaceId,
    ...POLL_60S,
  });

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <AlertTriangle className="h-4 w-4 text-orange-500" />
          At-Risk Deals
        </CardTitle>
        {data && data.total > 0 && (
          <span className="text-sm text-muted-foreground">
            {formatCurrency(data.total_amount_at_risk)} at risk
          </span>
        )}
      </CardHeader>
      <CardContent>
        {isPending ? (
          <PageLoadingState message="Scoring deals…" />
        ) : isError ? (
          <PageErrorState
            message="Couldn't load at-risk deals."
            onRetry={() => void refetch()}
          />
        ) : !data.items.length ? (
          <PageEmptyState
            icon={<ShieldCheck className="h-10 w-10" />}
            title="No deals at risk"
            description="Every open deal looks healthy right now."
          />
        ) : (
          <ul className="divide-y">
            {data.items.map((deal) => (
              <AtRiskRow
                key={deal.opportunity_id}
                deal={deal}
                onSelect={onSelect}
              />
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function AtRiskRow({
  deal,
  onSelect,
}: {
  deal: AtRiskDeal;
  onSelect?: (opportunityId: string) => void;
}) {
  const content = (
    <>
      <div className="min-w-0 space-y-0.5 text-left">
        <div className="flex items-center gap-2">
          <p className="truncate text-sm font-medium">{deal.name}</p>
          <Badge className={cn("text-xs", HEALTH_BADGE[deal.deal_health])}>
            {deal.deal_health.replace("_", " ")}
          </Badge>
        </div>
        <p className="truncate text-xs text-muted-foreground">{deal.top_risk}</p>
      </div>
      <div className="shrink-0 text-right">
        {deal.amount != null && (
          <p className="text-sm font-medium">
            {formatCurrency(deal.amount, deal.currency)}
          </p>
        )}
        <p className="text-xs text-muted-foreground">
          Risk {deal.risk_score}/100
        </p>
      </div>
    </>
  );

  if (!onSelect) {
    return (
      <li className="flex items-center justify-between gap-3 py-3">{content}</li>
    );
  }

  return (
    <li>
      <button
        type="button"
        className="flex w-full cursor-pointer items-center justify-between gap-3 rounded-md px-2 py-3 hover:bg-muted/50"
        onClick={() => onSelect(deal.opportunity_id)}
      >
        {content}
      </button>
    </li>
  );
}
