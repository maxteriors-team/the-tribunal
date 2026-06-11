"use client";

import { useQuery } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { PageEmptyState, PageErrorState, PageLoadingState } from "@/components/ui/page-state";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { reviewsApi } from "@/lib/api/reviews";
import { queryKeys } from "@/lib/query-keys";
import { POLL_60S } from "@/lib/query-options";
import { cn } from "@/lib/utils";
import type { ReviewRequestStatus } from "@/types/review";

const statusStyles: Record<ReviewRequestStatus, string> = {
  pending: "bg-muted text-muted-foreground",
  sent: "bg-info/10 text-info",
  clicked: "bg-info/10 text-info",
  rated: "bg-warning/10 text-warning",
  completed: "bg-success/10 text-success",
  failed: "bg-destructive/10 text-destructive",
};

function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function ReviewRequestsTab() {
  const workspaceId = useWorkspaceId();

  const { data, isPending, isError, refetch } = useQuery({
    queryKey: queryKeys.reviews.requests(workspaceId ?? ""),
    queryFn: () => reviewsApi.listRequests(workspaceId!),
    enabled: !!workspaceId,
    ...POLL_60S,
  });

  if (isPending) {
    return <PageLoadingState message="Loading review requests…" />;
  }

  if (isError) {
    return (
      <PageErrorState
        message="We couldn't load review requests. Please try again."
        onRetry={() => refetch()}
      />
    );
  }

  const requests = data?.items ?? [];

  if (requests.length === 0) {
    return (
      <PageEmptyState
        title="No review requests yet"
        description="Requests are sent automatically after completed appointments when the engine is enabled in Settings."
      />
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Contact</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Rating</TableHead>
          <TableHead>Sent</TableHead>
          <TableHead>Rated</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {requests.map((req) => (
          <TableRow key={req.id}>
            <TableCell className="font-medium">
              {req.contact_name ?? `Contact #${req.contact_id}`}
            </TableCell>
            <TableCell>
              <Badge
                variant="secondary"
                className={cn(statusStyles[req.status])}
              >
                {req.status}
              </Badge>
              {req.error && (
                <span className="ml-2 text-xs text-destructive">
                  {req.error}
                </span>
              )}
            </TableCell>
            <TableCell>{req.rating ? `${req.rating}★` : "—"}</TableCell>
            <TableCell className="text-muted-foreground">
              {formatDate(req.sent_at)}
            </TableCell>
            <TableCell className="text-muted-foreground">
              {formatDate(req.rated_at)}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
