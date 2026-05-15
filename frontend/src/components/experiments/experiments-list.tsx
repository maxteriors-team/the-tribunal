"use client";

import { useState } from "react";
import Link from "next/link";
import { motion, AnimatePresence } from "motion/react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  MoreHorizontal,
  Play,
  Pause,
  Trash2,
  FlaskConical,
  Trophy,
  CheckCircle2,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
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
import { Progress } from "@/components/ui/progress";
import { PageEmptyState } from "@/components/ui/page-state";
import {
  ResourceListHeader,
  ResourceListStats,
  ResourceListSearch,
  ResourceListLoading,
  ResourceListError,
  ResourceListPagination,
  ResourceListLayout,
} from "@/components/resource-list";
import { messageTestStatusColors } from "@/lib/status-colors";
import { useWorkspaceId } from "@/hooks/use-workspace-id";
import type { MessageTest } from "@/types";
import { messageTestsApi } from "@/lib/api/message-tests";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { formatNumber } from "@/lib/utils/number";

export function ExperimentsList() {
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();

  const { data: testsData, isPending, error } = useQuery({
    queryKey: ["message-tests", workspaceId],
    queryFn: () => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      return messageTestsApi.list(workspaceId);
    },
    enabled: !!workspaceId,
  });

  const tests = testsData?.items ?? [];

  const pauseMutation = useMutation({
    mutationFn: (id: string) => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      return messageTestsApi.pause(workspaceId, id);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["message-tests", workspaceId] });
      toast.success("Test paused");
    },
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Failed to pause test")),
  });

  const startMutation = useMutation({
    mutationFn: (id: string) => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      return messageTestsApi.start(workspaceId, id);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["message-tests", workspaceId] });
      toast.success("Test started");
    },
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Failed to start test")),
  });

  const completeMutation = useMutation({
    mutationFn: (id: string) => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      return messageTestsApi.complete(workspaceId, id);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["message-tests", workspaceId] });
      toast.success("Test completed");
    },
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Failed to complete test")),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      return messageTestsApi.delete(workspaceId, id);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["message-tests", workspaceId] });
      toast.success("Test deleted");
    },
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Failed to delete test")),
  });

  const filteredTests = tests.filter((test) => {
    const matchesSearch = test.name.toLowerCase().includes(searchQuery.toLowerCase());
    const matchesStatus = statusFilter === "all" || test.status === statusFilter;
    return matchesSearch && matchesStatus;
  });

  const getResponseRate = (test: MessageTest) => {
    if (test.messages_sent === 0) return 0;
    return Math.round((test.replies_received / test.messages_sent) * 100);
  };

  if (isPending) return <ResourceListLoading />;

  if (error) {
    return (
      <ResourceListError
        resourceName="experiments"
        onRetry={() => queryClient.invalidateQueries({ queryKey: ["message-tests", workspaceId] })}
      />
    );
  }

  return (
    <ResourceListLayout
      header={
        <ResourceListHeader
          title="Message Experiments"
          subtitle="A/B test your outreach messages to find what works best"
          action={
            <Button asChild>
              <Link href="/experiments/new">
                <FlaskConical className="mr-2 size-4" />
                New Experiment
              </Link>
            </Button>
          }
        />
      }
      stats={
        <ResourceListStats
          stats={[
            { label: "Total Experiments", value: tests.length },
            { label: "Running", value: tests.filter((t) => t.status === "running").length },
            { label: "Total Variants", value: tests.reduce((sum, t) => sum + t.total_variants, 0) },
            {
              label: "Avg Response Rate",
              value: `${tests.length > 0
                ? Math.round(tests.reduce((sum, t) => sum + getResponseRate(t), 0) / tests.length)
                : 0}%`,
            },
          ]}
        />
      }
      filterBar={
        <ResourceListSearch
          searchQuery={searchQuery}
          onSearchChange={setSearchQuery}
          placeholder="Search experiments..."
          filters={
            <Select value={statusFilter} onValueChange={setStatusFilter}>
              <SelectTrigger className="w-[140px]">
                <SelectValue placeholder="Status" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Status</SelectItem>
                <SelectItem value="draft">Draft</SelectItem>
                <SelectItem value="running">Running</SelectItem>
                <SelectItem value="paused">Paused</SelectItem>
                <SelectItem value="completed">Completed</SelectItem>
              </SelectContent>
            </Select>
          }
        />
      }
      emptyState={
        <PageEmptyState
          icon={<FlaskConical className="size-12" />}
          title="No experiments yet"
          description="Create your first A/B test to start optimizing your outreach"
          action={
            <Button asChild>
              <Link href="/experiments/new">Create Experiment</Link>
            </Button>
          }
        />
      }
      isEmpty={filteredTests.length === 0}
      pagination={
        filteredTests.length > 0 ? (
          <ResourceListPagination
            filteredCount={filteredTests.length}
            totalCount={tests.length}
            resourceName="experiments"
          />
        ) : undefined
      }
    >
      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Experiment</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Variants</TableHead>
                <TableHead>Progress</TableHead>
                <TableHead>Response Rate</TableHead>
                <TableHead>Winner</TableHead>
                <TableHead className="w-[50px]"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <AnimatePresence mode="popLayout">
                {filteredTests.map((test) => {
                  const progress =
                    test.total_contacts > 0
                      ? (test.messages_sent / test.total_contacts) * 100
                      : 0;

                  return (
                    <motion.tr
                      key={test.id}
                      layout
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0 }}
                      className="group cursor-pointer hover:bg-muted/50"
                    >
                      <TableCell>
                        <Link href={`/experiments/${test.id}`} className="block">
                          <div className="font-medium">{test.name}</div>
                          <div className="text-sm text-muted-foreground line-clamp-1">
                            {test.description || "No description"}
                          </div>
                        </Link>
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline" className={messageTestStatusColors[test.status]}>
                          {test.status}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          <FlaskConical className="size-4 text-muted-foreground" />
                          <span>{test.total_variants} variants</span>
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="space-y-1">
                          <Progress value={progress} className="h-2 w-24" />
                          <div className="text-xs text-muted-foreground">
                            {formatNumber(test.messages_sent)} / {formatNumber(test.total_contacts)}
                          </div>
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="font-medium">{getResponseRate(test)}%</div>
                      </TableCell>
                      <TableCell>
                        {test.winning_variant_id ? (
                          <Badge variant="secondary" className="bg-success/10 text-success">
                            <Trophy className="mr-1 size-3" />
                            Winner selected
                          </Badge>
                        ) : test.status === "completed" ? (
                          <span className="text-sm text-muted-foreground">Pending</span>
                        ) : (
                          <span className="text-sm text-muted-foreground">-</span>
                        )}
                      </TableCell>
                      <TableCell>
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="opacity-0 group-hover:opacity-100"
                            >
                              <MoreHorizontal className="size-4" />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            {test.status === "running" ? (
                              <DropdownMenuItem onSelect={() => pauseMutation.mutate(test.id)}>
                                <Pause className="mr-2 size-4" />
                                Pause
                              </DropdownMenuItem>
                            ) : test.status === "paused" || test.status === "draft" ? (
                              <DropdownMenuItem onSelect={() => startMutation.mutate(test.id)}>
                                <Play className="mr-2 size-4" />
                                {test.status === "draft" ? "Start" : "Resume"}
                              </DropdownMenuItem>
                            ) : null}
                            {(test.status === "running" || test.status === "paused") && (
                              <DropdownMenuItem onSelect={() => completeMutation.mutate(test.id)}>
                                <CheckCircle2 className="mr-2 size-4" />
                                Complete
                              </DropdownMenuItem>
                            )}
                            <DropdownMenuSeparator />
                            <DropdownMenuItem
                              variant="destructive"
                              onSelect={() => deleteMutation.mutate(test.id)}
                            >
                              <Trash2 className="mr-2 size-4" />
                              Delete
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </TableCell>
                    </motion.tr>
                  );
                })}
              </AnimatePresence>
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </ResourceListLayout>
  );
}
