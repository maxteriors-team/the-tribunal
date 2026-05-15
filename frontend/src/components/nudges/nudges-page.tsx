"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { formatDayMonth, formatRelative, addDays } from "@/lib/utils/date";
import Link from "next/link";
import {
  Bell,
  Check,
  X,
  Clock,
  Send,
  AlarmClock,
  Inbox,
  CalendarIcon,
  Mail,
} from "lucide-react";

import { nudgesApi } from "@/lib/api/nudges";
import type { HumanNudge, NudgeStatus, SuggestedAction } from "@/types/nudge";
import { useWorkspaceId } from "@/hooks/use-workspace-id";
import { queryKeys } from "@/lib/query-keys";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PageEmptyState } from "@/components/ui/page-state";
import { Skeleton } from "@/components/ui/skeleton";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Calendar } from "@/components/ui/calendar";
import { cn } from "@/lib/utils";
import { getApiErrorMessage } from "@/lib/utils/errors";

const NUDGE_TYPE_EMOJI: Record<string, string> = {
  birthday: "🎂",
  anniversary: "💍",
  cooling: "🔄",
  custom: "📅",
  follow_up: "📋",
  deal_milestone: "🎯",
};

const SUGGESTED_ACTION_LABELS: Record<SuggestedAction, string> = {
  send_card: "Send Card",
  call: "Call",
  text: "Text",
  email: "Email",
};

const PRIORITY_STYLES: Record<string, string> = {
  high: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
  medium: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200",
  low: "bg-gray-100 text-gray-800 dark:bg-gray-900 dark:text-gray-200",
};

const STATUS_TABS: { value: NudgeStatus; label: string }[] = [
  { value: "pending", label: "Pending" },
  { value: "sent", label: "Sent" },
  { value: "acted", label: "Acted" },
  { value: "dismissed", label: "Dismissed" },
  { value: "snoozed", label: "Snoozed" },
];

const PAGE_SIZE = 20;

export function NudgesPage() {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<NudgeStatus>("pending");
  const [page, setPage] = useState(1);

  const { data: stats, isPending: statsLoading } = useQuery({
    queryKey: queryKeys.nudges.stats(workspaceId ?? ""),
    queryFn: () => {
      if (!workspaceId) throw new Error("No workspace");
      return nudgesApi.getStats(workspaceId);
    },
    enabled: !!workspaceId,
  });

  const { data: nudgeList, isPending: listLoading } = useQuery({
    queryKey: queryKeys.nudges.list(workspaceId ?? "", statusFilter, page),
    queryFn: () => {
      if (!workspaceId) throw new Error("No workspace");
      return nudgesApi.list(workspaceId, {
        status: statusFilter,
        page,
        page_size: PAGE_SIZE,
      });
    },
    enabled: !!workspaceId,
  });

  const invalidateNudges = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.nudges.root() });
    void queryClient.invalidateQueries({ queryKey: queryKeys.nudges.statsRoot() });
  };

  const actMutation = useMutation({
    mutationFn: ({ nudgeId, actionTaken }: { nudgeId: string; actionTaken?: string }) => {
      if (!workspaceId) throw new Error("No workspace");
      return nudgesApi.act(workspaceId, nudgeId, actionTaken);
    },
    onSuccess: (_data, variables) => {
      toast.success(variables.actionTaken === "send_card" ? "Card sent!" : "Marked as done");
      invalidateNudges();
    },
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Failed")),
  });

  const dismissMutation = useMutation({
    mutationFn: (nudgeId: string) => {
      if (!workspaceId) throw new Error("No workspace");
      return nudgesApi.dismiss(workspaceId, nudgeId);
    },
    onSuccess: () => {
      toast.success("Dismissed");
      invalidateNudges();
    },
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Failed to dismiss")),
  });

  const snoozeMutation = useMutation({
    mutationFn: ({ nudgeId, snoozeUntil }: { nudgeId: string; snoozeUntil: string }) => {
      if (!workspaceId) throw new Error("No workspace");
      return nudgesApi.snooze(workspaceId, nudgeId, snoozeUntil);
    },
    onSuccess: (_data, variables) => {
      toast.success(`Snoozed until ${formatDayMonth(variables.snoozeUntil)}`);
      invalidateNudges();
    },
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Failed to snooze")),
  });

  const totalPages = nudgeList ? Math.ceil(nudgeList.total / PAGE_SIZE) : 0;

  return (
    <div className="h-full overflow-y-auto">
      <div className="space-y-6 p-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Nudges</h1>
            <p className="text-sm text-muted-foreground">
              Relationship reminders and follow-up prompts
            </p>
          </div>
          {stats && stats.pending > 0 && (
            <div className="flex items-center gap-2 rounded-lg border bg-warning/10 px-4 py-2">
              <Bell className="h-5 w-5 text-warning" />
              <span className="text-sm font-medium">
                {stats.pending} pending nudge{stats.pending !== 1 && "s"}
              </span>
            </div>
          )}
        </div>

        {/* Stats Cards */}
        <div className="grid gap-4 md:grid-cols-4">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium">Pending</CardTitle>
              <Clock className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {statsLoading ? "-" : (stats?.pending ?? 0)}
              </div>
              <p className="text-xs text-muted-foreground">Awaiting action</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium">Sent</CardTitle>
              <Send className="h-4 w-4 text-blue-500" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {statsLoading ? "-" : (stats?.sent ?? 0)}
              </div>
              <p className="text-xs text-muted-foreground">Delivered</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium">Acted</CardTitle>
              <Check className="h-4 w-4 text-green-500" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {statsLoading ? "-" : (stats?.acted ?? 0)}
              </div>
              <p className="text-xs text-muted-foreground">Completed</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium">Total</CardTitle>
              <Bell className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {statsLoading ? "-" : (stats?.total ?? 0)}
              </div>
              <p className="text-xs text-muted-foreground">This month</p>
            </CardContent>
          </Card>
        </div>

        {/* Filter Tabs + List */}
        <Tabs
          value={statusFilter}
          onValueChange={(v) => {
            setStatusFilter(v as NudgeStatus);
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
                <NudgeListSkeleton />
              ) : !nudgeList?.items.length ? (
                <NudgeEmptyState status={tab.value} />
              ) : (
                <div className="space-y-3">
                  {nudgeList.items.map((nudge) => (
                    <NudgeCard
                      key={nudge.id}
                      nudge={nudge}
                      onAct={(actionTaken) => actMutation.mutate({ nudgeId: nudge.id, actionTaken })}
                      onDismiss={() => dismissMutation.mutate(nudge.id)}
                      onSnooze={(date) =>
                        snoozeMutation.mutate({
                          nudgeId: nudge.id,
                          snoozeUntil: date.toISOString(),
                        })
                      }
                      isActing={actMutation.isPending}
                      isDismissing={dismissMutation.isPending}
                    />
                  ))}

                  {/* Pagination */}
                  {totalPages > 1 && (
                    <div className="flex items-center justify-between pt-4">
                      <p className="text-sm text-muted-foreground">
                        Page {page} of {totalPages} ({nudgeList.total} nudge
                        {nudgeList.total !== 1 && "s"})
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
    </div>
  );
}

function NudgeCard({
  nudge,
  onAct,
  onDismiss,
  onSnooze,
  isActing,
  isDismissing,
}: {
  nudge: HumanNudge;
  onAct: (actionTaken?: string) => void;
  onDismiss: () => void;
  onSnooze: (date: Date) => void;
  isActing: boolean;
  isDismissing: boolean;
}) {
  const [snoozeOpen, setSnoozeOpen] = useState(false);
  const emoji = NUDGE_TYPE_EMOJI[nudge.nudge_type] ?? "📌";
  const isPending = nudge.status === "pending";

  return (
    <Card>
      <CardContent className="flex items-start gap-4 p-4">
        {/* Emoji icon */}
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-muted text-xl">
          {emoji}
        </div>

        {/* Content */}
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <h3 className="font-medium leading-tight">{nudge.title}</h3>
              <p className="text-sm text-muted-foreground line-clamp-2">
                {nudge.message}
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-1.5">
              <Badge className={cn("text-xs", PRIORITY_STYLES[nudge.priority])}>
                {nudge.priority}
              </Badge>
              {nudge.suggested_action && (
                <Badge variant="outline" className="text-xs">
                  {SUGGESTED_ACTION_LABELS[nudge.suggested_action]}
                </Badge>
              )}
            </div>
          </div>

          {/* Contact + Due date row */}
          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            {nudge.contact_name && (
              <Link
                href={`/contacts/${nudge.contact_id}`}
                className="font-medium text-foreground hover:underline"
              >
                {nudge.contact_name}
                {nudge.contact_company && (
                  <span className="font-normal text-muted-foreground">
                    {" "}
                    · {nudge.contact_company}
                  </span>
                )}
              </Link>
            )}
            <span className="flex items-center gap-1">
              <CalendarIcon className="h-3 w-3" />
              {formatDueDate(nudge.due_date)}
            </span>
            {nudge.status === "snoozed" && nudge.snoozed_until && (
              <span className="flex items-center gap-1">
                <AlarmClock className="h-3 w-3" />
                Snoozed until {formatDayMonth(nudge.snoozed_until)}
              </span>
            )}
            {nudge.status !== "pending" && nudge.status !== "snoozed" && (
              <NudgeStatusBadge status={nudge.status} />
            )}
          </div>
        </div>

        {/* Actions */}
        {isPending && (
          <div className="flex shrink-0 items-center gap-1">
            {nudge.suggested_action === "send_card" ? (
              <>
                <Button
                  size="sm"
                  onClick={() => onAct("send_card")}
                  disabled={isActing}
                  title="Send Card"
                >
                  <Mail className="mr-1 h-3.5 w-3.5" />
                  Send Card
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => onAct()}
                  disabled={isActing}
                  title="Mark as done"
                >
                  <Check className="mr-1 h-3.5 w-3.5" />
                  Done
                </Button>
              </>
            ) : (
              <Button
                size="sm"
                variant="outline"
                onClick={() => onAct()}
                disabled={isActing}
                title="Mark as done"
              >
                <Check className="mr-1 h-3.5 w-3.5" />
                Done
              </Button>
            )}

            <Popover open={snoozeOpen} onOpenChange={setSnoozeOpen}>
              <PopoverTrigger asChild>
                <Button size="sm" variant="outline" title="Snooze">
                  <AlarmClock className="mr-1 h-3.5 w-3.5" />
                  Snooze
                </Button>
              </PopoverTrigger>
              <PopoverContent className="w-auto p-0" align="end">
                <div className="space-y-2 p-3">
                  <p className="text-sm font-medium">Snooze until</p>
                  <div className="flex flex-col gap-1">
                    {[
                      { label: "Tomorrow", days: 1 },
                      { label: "In 3 days", days: 3 },
                      { label: "Next week", days: 7 },
                    ].map((opt) => (
                      <Button
                        key={opt.days}
                        variant="ghost"
                        size="sm"
                        className="justify-start"
                        onClick={() => {
                          onSnooze(addDays(new Date(), opt.days));
                          setSnoozeOpen(false);
                        }}
                      >
                        {opt.label}
                      </Button>
                    ))}
                  </div>
                  <Calendar
                    mode="single"
                    disabled={(date) => date < new Date()}
                    onSelect={(date) => {
                      if (date) {
                        onSnooze(date);
                        setSnoozeOpen(false);
                      }
                    }}
                  />
                </div>
              </PopoverContent>
            </Popover>

            <Button
              size="sm"
              variant="ghost"
              onClick={onDismiss}
              disabled={isDismissing}
              title="Dismiss"
              className="text-muted-foreground hover:text-destructive"
            >
              <X className="h-3.5 w-3.5" />
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function NudgeStatusBadge({ status }: { status: string }) {
  switch (status) {
    case "sent":
      return (
        <Badge variant="secondary" className="text-xs">
          Sent
        </Badge>
      );
    case "acted":
      return (
        <Badge variant="default" className="bg-green-600 text-xs">
          Acted
        </Badge>
      );
    case "dismissed":
      return <Badge variant="destructive" className="text-xs">Dismissed</Badge>;
    default:
      return (
        <Badge variant="outline" className="text-xs">
          {status}
        </Badge>
      );
  }
}

function NudgeEmptyState({ status }: { status: string }) {
  return (
    <Card>
      <CardContent className="py-4">
        <PageEmptyState
          icon={<Inbox className="h-12 w-12" />}
          title={status === "pending" ? "All caught up!" : "No nudges"}
          description={
            status === "pending"
              ? "No nudges right now. When your contacts have upcoming birthdays or need follow-ups, they'll appear here."
              : `No ${status} nudges found.`
          }
        />
      </CardContent>
    </Card>
  );
}

function NudgeListSkeleton() {
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
              <Skeleton className="h-8 w-16" />
              <Skeleton className="h-8 w-18" />
              <Skeleton className="h-8 w-8" />
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function formatDueDate(dateStr: string): string {
  const due = new Date(dateStr);
  const now = new Date();
  const diffMs = due.getTime() - now.getTime();
  const diffDays = Math.round(diffMs / (1000 * 60 * 60 * 24));

  if (diffDays === 0) return "Today";
  if (diffDays === 1) return "Tomorrow";
  if (diffDays === -1) return "Yesterday";
  if (diffDays > 0 && diffDays <= 14) return `In ${diffDays} days`;
  if (diffDays < 0 && diffDays >= -14) return `${Math.abs(diffDays)} days ago`;

  return formatRelative(due);
}
