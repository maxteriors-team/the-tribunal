"use client";

import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { motion, AnimatePresence } from "motion/react";
import { formatDate, formatRelative } from "@/lib/utils/date";
import { getInitialsFromName } from "@/lib/utils/initials";
import { useInfiniteQuery } from "@tanstack/react-query";
import {
  Search,
  Phone,
  PhoneIncoming,
  PhoneOutgoing,
  PhoneMissed,
  Play,
  Clock,
  User,
  Bot,
  Download,
  Loader2,
  CalendarCheck,
  type LucideIcon,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
} from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { PageEmptyState, PageErrorState, PageLoadingState } from "@/components/ui/page-state";
import { ScrollArea } from "@/components/ui/scroll-area";
import { TranscriptViewer } from "@/components/calls/transcript-viewer";
import { useWorkspaceId } from "@/hooks/use-workspace-id";
import { queryKeys } from "@/lib/query-keys";
import { callStatusColors } from "@/lib/status-colors";
import { callsApi } from "@/lib/api/calls";

const statusConfig: Record<string, { label: string; color: string; icon: LucideIcon }> = {
  completed: { label: "Completed", color: callStatusColors.completed, icon: Phone },
  in_progress: { label: "In Progress", color: callStatusColors.in_progress, icon: Phone },
  initiated: { label: "Initiated", color: callStatusColors.initiated, icon: Phone },
  ringing: { label: "Ringing", color: callStatusColors.ringing, icon: Phone },
  no_answer: { label: "No Answer", color: callStatusColors.no_answer, icon: PhoneMissed },
  busy: { label: "Busy", color: callStatusColors.busy, icon: PhoneMissed },
  failed: { label: "Failed", color: callStatusColors.failed, icon: PhoneMissed },
};

function formatDuration(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

export function CallsList() {
  const [searchQuery, setSearchQuery] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [directionFilter, setDirectionFilter] = useState<string>("all");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const pageSize = 50;

  const workspaceId = useWorkspaceId();
  const sentinelRef = useRef<HTMLDivElement>(null);

  // Debounce search input
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(searchQuery);
    }, 300);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  const { data, isPending, error, fetchNextPage, hasNextPage, isFetchingNextPage } = useInfiniteQuery({
    queryKey: queryKeys.calls.listFiltered(workspaceId ?? "", directionFilter, statusFilter, debouncedSearch),
    queryFn: ({ pageParam }) => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      return callsApi.list(workspaceId, {
        page: pageParam,
        page_size: pageSize,
        direction: directionFilter !== "all" ? directionFilter as "inbound" | "outbound" : undefined,
        status: statusFilter !== "all" ? statusFilter : undefined,
        search: debouncedSearch || undefined,
      });
    },
    initialPageParam: 1,
    getNextPageParam: (lastPage) => {
      if (lastPage.page < lastPage.pages) return lastPage.page + 1;
      return undefined;
    },
    enabled: !!workspaceId,
  });

  const filteredCalls = useMemo(
    () => data?.pages.flatMap((p) => p.items) ?? [],
    [data?.pages],
  );
  const firstPage = data?.pages[0];
  const totalCalls = firstPage?.total ?? 0;
  const completedCalls = firstPage?.completed_count ?? 0;
  const totalDuration = firstPage?.total_duration_seconds ?? 0;
  const avgDuration = completedCalls > 0 ? Math.round(totalDuration / completedCalls) : 0;

  // Infinite scroll: observe sentinel element
  const handleObserver = useCallback(
    (entries: IntersectionObserverEntry[]) => {
      const [entry] = entries;
      if (entry.isIntersecting && hasNextPage && !isFetchingNextPage) {
        fetchNextPage();
      }
    },
    [hasNextPage, isFetchingNextPage, fetchNextPage],
  );

  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    const observer = new IntersectionObserver(handleObserver, { threshold: 0.1 });
    observer.observe(el);
    return () => observer.disconnect();
  }, [handleObserver]);

  if (isPending) {
    return <PageLoadingState className="h-96" />;
  }

  if (error) {
    return (
      <PageErrorState
        className="h-96"
        message={(error as Error).message || "Failed to load calls"}
      />
    );
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Calls</h1>
          <p className="text-muted-foreground">
            View and manage all voice calls
          </p>
        </div>
        <Button variant="outline">
          <Download className="mr-2 size-4" />
          Export
        </Button>
      </div>

      {/* Stats Cards */}
      <motion.div
        className="grid gap-4 md:grid-cols-4"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ staggerChildren: 0.1 }}
      >
        {[
          { label: "Total Calls", value: totalCalls, icon: Phone },
          { label: "Completed", value: completedCalls, icon: Phone },
          { label: "Total Duration", value: formatDuration(totalDuration), icon: Clock },
          { label: "Avg Duration", value: formatDuration(avgDuration), icon: Clock },
        ].map((stat) => (
          <Card key={stat.label}>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardDescription>{stat.label}</CardDescription>
              <stat.icon className="size-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{stat.value}</div>
            </CardContent>
          </Card>
        ))}
      </motion.div>

      {/* Filters */}
      <Card>
        <CardContent className="pt-6">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                placeholder="Search by contact name..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-10"
              />
            </div>
            <div className="flex gap-2">
              <Select value={directionFilter} onValueChange={setDirectionFilter}>
                <SelectTrigger className="w-[140px]">
                  <SelectValue placeholder="Direction" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Directions</SelectItem>
                  <SelectItem value="inbound">Inbound</SelectItem>
                  <SelectItem value="outbound">Outbound</SelectItem>
                </SelectContent>
              </Select>
              <Select value={statusFilter} onValueChange={setStatusFilter}>
                <SelectTrigger className="w-[140px]">
                  <SelectValue placeholder="Status" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Status</SelectItem>
                  <SelectItem value="completed">Completed</SelectItem>
                  <SelectItem value="no_answer">No Answer</SelectItem>
                  <SelectItem value="busy">Busy</SelectItem>
                  <SelectItem value="failed">Failed</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Calls Table */}
      <Card>
        <CardContent className="p-0">
          {filteredCalls.length === 0 ? (
            <PageEmptyState
              className="py-12"
              icon={<Phone className="size-12" />}
              title="No calls found"
              description="Voice calls will appear here once made"
            />
          ) : (
            <ScrollArea className="h-[calc(100vh-480px)] min-h-[300px]">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Contact</TableHead>
                  <TableHead>Direction</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Duration</TableHead>
                  <TableHead>Agent</TableHead>
                  <TableHead>Time</TableHead>
                  <TableHead className="w-[100px]">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                <AnimatePresence mode="popLayout">
                  {filteredCalls.map((call) => {
                    const status = statusConfig[call.status] || statusConfig.completed;
                    const DirectionIcon =
                      call.direction === "inbound" ? PhoneIncoming : PhoneOutgoing;
                    const displayName = call.contact_name || (call.direction === "inbound" ? call.from_number : call.to_number) || "Unknown";
                    const displayNumber = (call.direction === "inbound" ? call.from_number : call.to_number) || "";

                    return (
                      <motion.tr
                        key={call.id}
                        layout
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        className="group"
                      >
                        <TableCell>
                          <div className="flex items-center gap-3">
                            <Avatar className="size-8">
                              <AvatarFallback className="text-xs">
                                {getInitialsFromName(call.contact_name || displayNumber)}
                              </AvatarFallback>
                            </Avatar>
                            <div>
                              <div className="font-medium text-sm">
                                {call.direction === "inbound" ? "From" : "To"} {displayName}
                              </div>
                              {call.contact_name && displayNumber && (
                                <div className="text-xs text-muted-foreground font-mono">
                                  {displayNumber}
                                </div>
                              )}
                            </div>
                          </div>
                        </TableCell>
                        <TableCell>
                          <div className="flex items-center gap-2">
                            <DirectionIcon
                              className={`size-4 ${
                                call.direction === "inbound"
                                  ? "text-info"
                                  : "text-success"
                              }`}
                            />
                            <span className="capitalize">{call.direction}</span>
                          </div>
                        </TableCell>
                        <TableCell>
                          <div className="flex items-center gap-1.5">
                            <Badge variant="outline" className={status.color}>
                              {status.label}
                            </Badge>
                            {call.booking_outcome === "success" && (
                              <Badge variant="outline" className="bg-success/10 text-success border-success/20">
                                <CalendarCheck className="size-3 mr-1" />
                                Booked
                              </Badge>
                            )}
                          </div>
                        </TableCell>
                        <TableCell>
                          {call.duration_seconds
                            ? formatDuration(call.duration_seconds)
                            : "-"}
                        </TableCell>
                        <TableCell>
                          {call.is_ai || call.agent_id ? (
                            <div className="flex items-center gap-2">
                              <Bot className="size-4 text-primary" />
                              <span className="text-sm">{call.agent_name || "AI Agent"}</span>
                            </div>
                          ) : (
                            <div className="flex items-center gap-2">
                              <User className="size-4 text-muted-foreground" />
                              <span className="text-sm text-muted-foreground">
                                Manual
                              </span>
                            </div>
                          )}
                        </TableCell>
                        <TableCell>
                          <div className="text-sm">
                            {formatRelative(call.created_at)}
                          </div>
                          <div className="text-xs text-muted-foreground">
                            {formatDate(call.created_at, { pattern: "MMM d, h:mm a" })}
                          </div>
                        </TableCell>
                        <TableCell>
                          <div className="flex items-center gap-1">
                            {call.recording_url && (
                              <Button
                                variant="ghost"
                                size="icon-sm"
                                className="opacity-0 group-hover:opacity-100"
                              >
                                <Play className="size-4" />
                              </Button>
                            )}
                            <Dialog>
                              <DialogTrigger asChild>
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  className="opacity-0 group-hover:opacity-100"
                                >
                                  View
                                </Button>
                              </DialogTrigger>
                              <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
                                <DialogHeader>
                                  <DialogTitle>Call Details</DialogTitle>
                                  <DialogDescription>
                                    {displayName} -{" "}
                                    {formatDate(call.created_at, {
                                      pattern: "MMMM d, yyyy 'at' h:mm a",
                                    })}
                                  </DialogDescription>
                                </DialogHeader>
                                <div className="space-y-4">
                                  <div className="grid grid-cols-2 gap-4 text-sm">
                                    <div>
                                      <span className="text-muted-foreground">
                                        Direction:
                                      </span>{" "}
                                      <span className="capitalize">
                                        {call.direction}
                                      </span>
                                    </div>
                                    <div>
                                      <span className="text-muted-foreground">
                                        Status:
                                      </span>{" "}
                                      {status.label}
                                    </div>
                                    <div>
                                      <span className="text-muted-foreground">
                                        Duration:
                                      </span>{" "}
                                      {call.duration_seconds
                                        ? formatDuration(call.duration_seconds)
                                        : "-"}
                                    </div>
                                    <div>
                                      <span className="text-muted-foreground">
                                        Agent:
                                      </span>{" "}
                                      {call.is_ai || call.agent_id ? (call.agent_name || "AI Agent") : "Manual"}
                                    </div>
                                    {call.booking_outcome && (
                                      <div>
                                        <span className="text-muted-foreground">
                                          Booking:
                                        </span>{" "}
                                        <Badge variant="outline" className={call.booking_outcome === "success" ? "bg-success/10 text-success border-success/20" : ""}>
                                          {call.booking_outcome === "success" ? "Booked" : call.booking_outcome}
                                        </Badge>
                                      </div>
                                    )}
                                    <div>
                                      <span className="text-muted-foreground">
                                        From:
                                      </span>{" "}
                                      <span className="font-mono">{call.from_number || "N/A"}</span>
                                    </div>
                                    <div>
                                      <span className="text-muted-foreground">
                                        To:
                                      </span>{" "}
                                      <span className="font-mono">{call.to_number || "N/A"}</span>
                                    </div>
                                  </div>
                                  {call.transcript && (
                                    <div className="space-y-2">
                                      <h4 className="font-medium">Transcript</h4>
                                      <TranscriptViewer
                                        transcript={call.transcript}
                                        maxHeight="400px"
                                      />
                                    </div>
                                  )}
                                  {call.recording_url && (
                                    <div className="space-y-2">
                                      <h4 className="font-medium">Recording</h4>
                                      <audio controls className="w-full">
                                        <source
                                          src={call.recording_url}
                                          type="audio/mpeg"
                                        />
                                      </audio>
                                    </div>
                                  )}
                                </div>
                              </DialogContent>
                            </Dialog>
                          </div>
                        </TableCell>
                      </motion.tr>
                    );
                  })}
                </AnimatePresence>
              </TableBody>
            </Table>
            {/* Sentinel for infinite scroll */}
            <div ref={sentinelRef} className="h-1" />
            {isFetchingNextPage && (
              <div className="flex items-center justify-center py-4">
                <Loader2 className="size-5 animate-spin text-muted-foreground" />
                <span className="ml-2 text-sm text-muted-foreground">Loading more calls...</span>
              </div>
            )}
            </ScrollArea>
          )}
        </CardContent>
      </Card>

      {/* Summary */}
      <div className="text-sm text-muted-foreground text-center">
        Showing {filteredCalls.length} of {totalCalls} calls
        {hasNextPage && " — scroll down for more"}
      </div>
    </div>
  );
}
