"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  ClipboardCheck,
  Clock,
  Check,
  X,
  AlertTriangle,
  Zap,
} from "lucide-react";

import { pendingActionsApi } from "@/lib/api/pending-actions";
import type { PendingActionStatus } from "@/types/pending-action";
import { useWorkspaceId } from "@/hooks/use-workspace-id";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PageEmptyState } from "@/components/ui/page-state";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { PendingActionCard } from "./pending-action-card";

type TabStatus = PendingActionStatus | "all";

const STATUS_TABS: { value: TabStatus; label: string }[] = [
  { value: "all", label: "All" },
  { value: "pending", label: "Pending" },
  { value: "approved", label: "Approved" },
  { value: "rejected", label: "Rejected" },
  { value: "expired", label: "Expired" },
];

const PAGE_SIZE = 20;

export function PendingActionsPage() {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<TabStatus>("pending");
  const [page, setPage] = useState(1);
  const [rejectActionId, setRejectActionId] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState("");

  const { data: stats, isPending: statsLoading } = useQuery({
    queryKey: ["pendingActionStats", workspaceId],
    queryFn: () => {
      if (!workspaceId) throw new Error("No workspace");
      return pendingActionsApi.getStats(workspaceId);
    },
    enabled: !!workspaceId,
  });

  const { data: actionList, isPending: listLoading } = useQuery({
    queryKey: ["pendingActions", workspaceId, statusFilter, page],
    queryFn: () => {
      if (!workspaceId) throw new Error("No workspace");
      return pendingActionsApi.list(workspaceId, {
        status: statusFilter === "all" ? undefined : statusFilter,
        page,
        page_size: PAGE_SIZE,
      });
    },
    enabled: !!workspaceId,
  });

  const invalidateActions = () => {
    void queryClient.invalidateQueries({ queryKey: ["pendingActions"] });
    void queryClient.invalidateQueries({ queryKey: ["pendingActionStats"] });
  };

  const approveMutation = useMutation({
    mutationFn: (actionId: string) => {
      if (!workspaceId) throw new Error("No workspace");
      return pendingActionsApi.approve(workspaceId, actionId);
    },
    onSuccess: () => {
      toast.success("Action approved");
      invalidateActions();
    },
    onError: (err: unknown) =>
      toast.error(getApiErrorMessage(err, "Failed to approve action")),
  });

  const rejectMutation = useMutation({
    mutationFn: ({ actionId, reason }: { actionId: string; reason?: string }) => {
      if (!workspaceId) throw new Error("No workspace");
      return pendingActionsApi.reject(workspaceId, actionId, reason);
    },
    onSuccess: () => {
      toast.success("Action rejected");
      invalidateActions();
      setRejectActionId(null);
      setRejectReason("");
    },
    onError: (err: unknown) =>
      toast.error(getApiErrorMessage(err, "Failed to reject action")),
  });

  const totalPages = actionList ? Math.ceil(actionList.total / PAGE_SIZE) : 0;

  return (
    <div className="h-full overflow-y-auto">
      <div className="space-y-6 p-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Pending Actions</h1>
            <p className="text-sm text-muted-foreground">
              Review and approve AI agent actions before they execute
            </p>
          </div>
          {stats && stats.pending > 0 && (
            <div className="flex items-center gap-2 rounded-lg border bg-warning/10 px-4 py-2">
              <Clock className="h-5 w-5 text-warning" />
              <span className="text-sm font-medium">
                {stats.pending} pending action{stats.pending !== 1 && "s"}
              </span>
            </div>
          )}
        </div>

        {/* Stats Cards */}
        <div className="grid gap-4 md:grid-cols-5">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium">Pending</CardTitle>
              <Clock className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {statsLoading ? "-" : (stats?.pending ?? 0)}
              </div>
              <p className="text-xs text-muted-foreground">Awaiting review</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium">Approved</CardTitle>
              <Check className="h-4 w-4 text-green-500" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {statsLoading ? "-" : (stats?.approved ?? 0)}
              </div>
              <p className="text-xs text-muted-foreground">Approved</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium">Rejected</CardTitle>
              <X className="h-4 w-4 text-red-500" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {statsLoading ? "-" : (stats?.rejected ?? 0)}
              </div>
              <p className="text-xs text-muted-foreground">Rejected</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium">Expired</CardTitle>
              <AlertTriangle className="h-4 w-4 text-yellow-500" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {statsLoading ? "-" : (stats?.expired ?? 0)}
              </div>
              <p className="text-xs text-muted-foreground">Timed out</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium">Executed</CardTitle>
              <Zap className="h-4 w-4 text-blue-500" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {statsLoading ? "-" : (stats?.executed ?? 0)}
              </div>
              <p className="text-xs text-muted-foreground">Completed</p>
            </CardContent>
          </Card>
        </div>

        {/* Filter Tabs + List */}
        <Tabs
          value={statusFilter}
          onValueChange={(v) => {
            setStatusFilter(v as TabStatus);
            setPage(1);
          }}
        >
          <TabsList>
            {STATUS_TABS.map((tab) => (
              <TabsTrigger key={tab.value} value={tab.value}>
                {tab.label}
                {tab.value === "pending" && stats && stats.pending > 0 && (
                  <span className="ml-1.5 rounded-full bg-warning px-1.5 py-0.5 text-xs text-white">
                    {stats.pending}
                  </span>
                )}
              </TabsTrigger>
            ))}
          </TabsList>

          {STATUS_TABS.map((tab) => (
            <TabsContent key={tab.value} value={tab.value} className="mt-4">
              {listLoading ? (
                <ActionListSkeleton />
              ) : !actionList?.items.length ? (
                <ActionEmptyState status={tab.value} />
              ) : (
                <div className="space-y-3">
                  {actionList.items.map((action) => (
                    <PendingActionCard
                      key={action.id}
                      action={action}
                      onApprove={() => approveMutation.mutate(action.id)}
                      onReject={() => setRejectActionId(action.id)}
                      isApproving={approveMutation.isPending}
                      isRejecting={rejectMutation.isPending}
                    />
                  ))}

                  {/* Pagination */}
                  {totalPages > 1 && (
                    <div className="flex items-center justify-between pt-4">
                      <p className="text-sm text-muted-foreground">
                        Page {page} of {totalPages} ({actionList.total} action
                        {actionList.total !== 1 && "s"})
                      </p>
                      <div className="flex gap-2">
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={page <= 1}
                          onClick={() => setPage((p) => p - 1)}
                        >
                          Previous
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={page >= totalPages}
                          onClick={() => setPage((p) => p + 1)}
                        >
                          Next
                        </Button>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </TabsContent>
          ))}
        </Tabs>
      </div>

      {/* Reject Dialog */}
      <Dialog open={!!rejectActionId} onOpenChange={() => setRejectActionId(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Reject Action</DialogTitle>
            <DialogDescription>
              Optionally provide a reason for rejecting this action.
            </DialogDescription>
          </DialogHeader>
          <Textarea
            placeholder="Reason for rejection (optional)"
            value={rejectReason}
            onChange={(e) => setRejectReason(e.target.value)}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setRejectActionId(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() =>
                rejectActionId &&
                rejectMutation.mutate({
                  actionId: rejectActionId,
                  reason: rejectReason || undefined,
                })
              }
              disabled={rejectMutation.isPending}
            >
              {rejectMutation.isPending ? "Rejecting..." : "Reject"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function ActionEmptyState({ status }: { status: string }) {
  return (
    <Card>
      <CardContent className="py-4">
        <PageEmptyState
          icon={<ClipboardCheck className="h-12 w-12" />}
          title={status === "pending" ? "All caught up!" : "No actions"}
          description={
            status === "pending"
              ? "No pending actions to review. When your AI agents need approval, actions will appear here."
              : `No ${status === "all" ? "" : status} actions found.`
          }
        />
      </CardContent>
    </Card>
  );
}

function ActionListSkeleton() {
  return (
    <div className="space-y-3">
      {Array.from({ length: 5 }).map((_, i) => (
        <Card key={i}>
          <CardContent className="flex items-start gap-4 p-4">
            <Skeleton className="h-10 w-10 rounded-lg" />
            <div className="flex-1 space-y-2">
              <Skeleton className="h-4 w-48" />
              <Skeleton className="h-3 w-72" />
              <Skeleton className="h-3 w-32" />
            </div>
            <div className="flex gap-1">
              <Skeleton className="h-8 w-20" />
              <Skeleton className="h-8 w-18" />
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
