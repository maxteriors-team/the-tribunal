"use client";

import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { Search } from "lucide-react";

import { ResourceListPagination } from "@/components/resource-list";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { PageEmptyState } from "@/components/ui/page-state";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useDebouncedSearch } from "@/hooks/useDebouncedSearch";
import { usePagination } from "@/hooks/usePagination";
import { opportunitiesApi } from "@/lib/api/opportunities";
import { queryKeys } from "@/lib/query-keys";
import { opportunityStatusColors } from "@/lib/status-colors";
import { formatDate } from "@/lib/utils/date";
import type { OpportunityStatus } from "@/types";

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
  const pageSize = 50;
  const pagination = usePagination({ initialPageSize: pageSize });
  const search = useDebouncedSearch({ delay: 300, onDebouncedChange: () => pagination.reset() });

  const { data, isPending } = useQuery({
    queryKey: queryKeys.opportunities.list(workspaceId ?? "", {
      page: pagination.page,
      search: search.debouncedValue || undefined,
    }),
    queryFn: () =>
      opportunitiesApi.list(workspaceId, {
        page: pagination.page,
        page_size: pageSize,
        search: search.debouncedValue || undefined,
      }),
    enabled: !!workspaceId,
    placeholderData: keepPreviousData,
  });

  const totalPages = data?.pages ?? 1;

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
    <div className="flex h-full w-full flex-col">
      <div className="border-b p-4">
        <div className="relative max-w-sm">
          <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Search opportunities..."
            value={search.value}
            onChange={(e) => search.setValue(e.target.value)}
            className="pl-9"
          />
        </div>
      </div>

      <div className="w-full flex-1 overflow-auto">
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
                  <PageEmptyState
                    className="min-h-0 py-8"
                    title="No opportunities found"
                    description={
                      search.debouncedValue
                        ? "Try a different search term."
                        : undefined
                    }
                  />
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      {data && data.total > 0 && (
        <div className="border-t p-4">
          <ResourceListPagination
            filteredCount={data.items.length}
            totalCount={data.total}
            resourceName="opportunities"
            page={pagination.page}
            totalPages={totalPages}
            onPageChange={pagination.setPage}
          />
        </div>
      )}
    </div>
  );
}
