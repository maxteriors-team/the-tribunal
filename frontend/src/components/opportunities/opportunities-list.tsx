"use client";

import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { PageEmptyState } from "@/components/ui/page-state";
import { Skeleton } from "@/components/ui/skeleton";
import { opportunityStatusColors } from "@/lib/status-colors";
import { opportunitiesApi } from "@/lib/api/opportunities";
import { queryKeys } from "@/lib/query-keys";
import type { OpportunityStatus } from "@/types";
import { formatDate } from "@/lib/utils/date";

interface OpportunitiesListProps {
  workspaceId: string;
}

function formatCurrency(amount: number | undefined, currency: string) {
  if (!amount) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: currency,
  }).format(amount);
}

function getStageColor(probability: number): string {
  if (probability === 0) return "bg-destructive/10 text-destructive";
  if (probability < 50) return "bg-warning/10 text-warning";
  if (probability < 100) return "bg-info/10 text-info";
  return "bg-success/10 text-success";
}


export function OpportunitiesList({ workspaceId }: OpportunitiesListProps) {
  const [page] = React.useState(1);
  const [search] = React.useState("");

  const { data, isPending } = useQuery({
    queryKey: queryKeys.opportunities.list(workspaceId ?? "", page, search),
    queryFn: () =>
      opportunitiesApi.list(workspaceId, {
        page,
        page_size: 50,
        search: search || undefined,
      }),
    enabled: !!workspaceId,
  });

  if (isPending) {
    return (
      <div className="w-full h-full p-4 overflow-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Amount</TableHead>
              <TableHead>Probability</TableHead>
              <TableHead>Close Date</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {Array.from({ length: 10 }).map((_, i) => (
              <TableRow key={i}>
                <TableCell>
                  <Skeleton className="h-4 w-48" />
                </TableCell>
                <TableCell>
                  <Skeleton className="h-4 w-24" />
                </TableCell>
                <TableCell>
                  <Skeleton className="h-4 w-16" />
                </TableCell>
                <TableCell>
                  <Skeleton className="h-4 w-20" />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    );
  }

  return (
    <div className="w-full h-full overflow-auto">
      <Table>
        <TableHeader className="sticky top-0 bg-background">
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Amount</TableHead>
            <TableHead>Probability</TableHead>
            <TableHead>Expected Close</TableHead>
            <TableHead>Source</TableHead>
            <TableHead>Created</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {data?.items && data.items.length > 0 ? (
            data.items.map((opportunity) => (
              <TableRow key={opportunity.id} className="hover:bg-muted/50">
                <TableCell className="font-medium">{opportunity.name}</TableCell>
                <TableCell>
                  <Badge className={opportunityStatusColors[opportunity.status as OpportunityStatus] ?? "bg-info/10 text-info border-info/20"}>
                    {opportunity.status}
                  </Badge>
                </TableCell>
                <TableCell>{formatCurrency(opportunity.amount, opportunity.currency)}</TableCell>
                <TableCell>
                  <Badge className={getStageColor(opportunity.probability)}>
                    {opportunity.probability}%
                  </Badge>
                </TableCell>
                <TableCell>
                  {opportunity.expected_close_date
                    ? formatDate(opportunity.expected_close_date)
                    : "—"}
                </TableCell>
                <TableCell>{opportunity.source || "—"}</TableCell>
                <TableCell className="text-sm text-muted-foreground">
                  {formatDate(opportunity.created_at)}
                </TableCell>
              </TableRow>
            ))
          ) : (
            <TableRow>
              <TableCell colSpan={7} className="py-0">
                <PageEmptyState className="min-h-0 py-8" title="No opportunities found" />
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
    </div>
  );
}
