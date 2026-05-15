"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { formatRelative } from "@/lib/utils/date";
import { formatNumber } from "@/lib/utils/number";
import {
  Play,
  Pause,
  RotateCcw,
  Eye,
  MoreHorizontal,
  Check,
  X,
  AlertTriangle,
  FlaskConical,
  Loader2,
} from "lucide-react";

import {
  promptVersionsApi,
  type PromptVersionResponse,
} from "@/lib/api/prompt-versions";
import { useWorkspaceId } from "@/hooks/use-workspace-id";
import { queryKeys } from "@/lib/query-keys";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import { getApiErrorMessage } from "@/lib/utils/errors";

interface PromptVersionHistoryProps {
  agentId: string;
}

export function PromptVersionHistory({ agentId }: PromptVersionHistoryProps) {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();
  const [selectedVersion, setSelectedVersion] = useState<PromptVersionResponse | null>(null);

  const { data: versions, isPending } = useQuery({
    queryKey: queryKeys.agents.promptVersions(workspaceId ?? "", agentId),
    queryFn: () => {
      if (!workspaceId) throw new Error("No workspace");
      return promptVersionsApi.list(workspaceId, agentId, { page_size: 50 });
    },
    enabled: !!workspaceId,
  });

  const activateMutation = useMutation({
    mutationFn: (versionId: string) => {
      if (!workspaceId) throw new Error("No workspace");
      return promptVersionsApi.activate(workspaceId, agentId, versionId);
    },
    onSuccess: () => {
      toast.success("Version activated");
      void queryClient.invalidateQueries({ queryKey: queryKeys.agents.promptVersionsAll() });
    },
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Failed to activate version")),
  });

  const activateForTestingMutation = useMutation({
    mutationFn: (versionId: string) => {
      if (!workspaceId) throw new Error("No workspace");
      return promptVersionsApi.activateForTesting(workspaceId, agentId, versionId);
    },
    onSuccess: () => {
      toast.success("Version added to A/B test");
      void queryClient.invalidateQueries({ queryKey: queryKeys.agents.promptVersionsAll() });
    },
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Failed to activate for testing")),
  });

  const deactivateMutation = useMutation({
    mutationFn: (versionId: string) => {
      if (!workspaceId) throw new Error("No workspace");
      return promptVersionsApi.deactivate(workspaceId, agentId, versionId);
    },
    onSuccess: () => {
      toast.success("Version deactivated");
      void queryClient.invalidateQueries({ queryKey: queryKeys.agents.promptVersionsAll() });
    },
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Failed to deactivate version")),
  });

  const pauseMutation = useMutation({
    mutationFn: (versionId: string) => {
      if (!workspaceId) throw new Error("No workspace");
      return promptVersionsApi.pause(workspaceId, agentId, versionId);
    },
    onSuccess: () => {
      toast.success("Version paused");
      void queryClient.invalidateQueries({ queryKey: queryKeys.agents.promptVersionsAll() });
    },
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Failed to pause version")),
  });

  const resumeMutation = useMutation({
    mutationFn: (versionId: string) => {
      if (!workspaceId) throw new Error("No workspace");
      return promptVersionsApi.resume(workspaceId, agentId, versionId);
    },
    onSuccess: () => {
      toast.success("Version resumed");
      void queryClient.invalidateQueries({ queryKey: queryKeys.agents.promptVersionsAll() });
    },
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Failed to resume version")),
  });

  const eliminateMutation = useMutation({
    mutationFn: (versionId: string) => {
      if (!workspaceId) throw new Error("No workspace");
      return promptVersionsApi.eliminate(workspaceId, agentId, versionId);
    },
    onSuccess: () => {
      toast.success("Version eliminated from testing");
      void queryClient.invalidateQueries({ queryKey: queryKeys.agents.promptVersionsAll() });
    },
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Failed to eliminate version")),
  });

  const rollbackMutation = useMutation({
    mutationFn: (versionId: string) => {
      if (!workspaceId) throw new Error("No workspace");
      return promptVersionsApi.rollback(workspaceId, agentId, versionId);
    },
    onSuccess: () => {
      toast.success("Rolled back to this version");
      void queryClient.invalidateQueries({ queryKey: queryKeys.agents.promptVersionsAll() });
    },
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Failed to rollback")),
  });

  const getStatusBadge = (version: PromptVersionResponse) => {
    if (version.arm_status === "eliminated") {
      return (
        <Badge variant="destructive" className="text-xs">
          <X className="mr-1 h-3 w-3" />
          Eliminated
        </Badge>
      );
    }
    if (version.is_active && version.arm_status === "paused") {
      return (
        <Badge variant="secondary" className="text-xs">
          <Pause className="mr-1 h-3 w-3" />
          Paused
        </Badge>
      );
    }
    if (version.is_active) {
      return (
        <Badge variant="default" className="text-xs">
          <Check className="mr-1 h-3 w-3" />
          Active
        </Badge>
      );
    }
    return (
      <Badge variant="outline" className="text-xs">
        Inactive
      </Badge>
    );
  };

  const getBookingRate = (version: PromptVersionResponse) => {
    if (version.successful_calls === 0) return null;
    return (version.booked_appointments / version.successful_calls) * 100;
  };

  if (isPending) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!versions?.items.length) {
    return (
      <div className="flex flex-col items-center justify-center py-8 text-center">
        <FlaskConical className="mb-2 h-10 w-10 text-muted-foreground" />
        <p className="text-sm text-muted-foreground">No prompt versions found</p>
        <p className="text-xs text-muted-foreground">
          Versions are created automatically when you modify the agent prompt
        </p>
      </div>
    );
  }

  return (
    <>
      <div className="rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-16">Version</TableHead>
              <TableHead>Change Summary</TableHead>
              <TableHead className="w-24">Status</TableHead>
              <TableHead className="w-24 text-right">Calls</TableHead>
              <TableHead className="w-24 text-right">Booking Rate</TableHead>
              <TableHead className="w-36">Created</TableHead>
              <TableHead className="w-16"></TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {versions.items.map((version) => {
              const bookingRate = getBookingRate(version);
              return (
                <TableRow
                  key={version.id}
                  className={cn(
                    version.arm_status === "eliminated" && "opacity-50"
                  )}
                >
                  <TableCell className="font-mono">
                    v{version.version_number}
                    {version.is_baseline && (
                      <Badge variant="outline" className="ml-2 text-[10px]">
                        Baseline
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell className="max-w-xs truncate">
                    {version.change_summary || "No description"}
                  </TableCell>
                  <TableCell>{getStatusBadge(version)}</TableCell>
                  <TableCell className="text-right font-mono">
                    {formatNumber(version.total_calls)}
                  </TableCell>
                  <TableCell className="text-right font-mono">
                    {bookingRate !== null ? `${bookingRate.toFixed(1)}%` : "-"}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {formatRelative(version.created_at)}
                  </TableCell>
                  <TableCell>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="icon" className="h-8 w-8" aria-label="Version actions">
                          <MoreHorizontal className="h-4 w-4" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem onClick={() => setSelectedVersion(version)}>
                          <Eye className="mr-2 h-4 w-4" />
                          View Prompt
                        </DropdownMenuItem>
                        <DropdownMenuSeparator />
                        {!version.is_active && version.arm_status !== "eliminated" && (
                          <>
                            <DropdownMenuItem
                              onClick={() => activateMutation.mutate(version.id)}
                            >
                              <Play className="mr-2 h-4 w-4" />
                              Activate (Replace Current)
                            </DropdownMenuItem>
                            <DropdownMenuItem
                              onClick={() => activateForTestingMutation.mutate(version.id)}
                            >
                              <FlaskConical className="mr-2 h-4 w-4" />
                              Add to A/B Test
                            </DropdownMenuItem>
                          </>
                        )}
                        {version.is_active && version.arm_status === "active" && (
                          <>
                            <DropdownMenuItem
                              onClick={() => pauseMutation.mutate(version.id)}
                            >
                              <Pause className="mr-2 h-4 w-4" />
                              Pause
                            </DropdownMenuItem>
                            <DropdownMenuItem
                              onClick={() => deactivateMutation.mutate(version.id)}
                            >
                              <X className="mr-2 h-4 w-4" />
                              Deactivate
                            </DropdownMenuItem>
                          </>
                        )}
                        {version.is_active && version.arm_status === "paused" && (
                          <DropdownMenuItem
                            onClick={() => resumeMutation.mutate(version.id)}
                          >
                            <Play className="mr-2 h-4 w-4" />
                            Resume
                          </DropdownMenuItem>
                        )}
                        {version.arm_status !== "eliminated" && (
                          <>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem
                              onClick={() => rollbackMutation.mutate(version.id)}
                            >
                              <RotateCcw className="mr-2 h-4 w-4" />
                              Rollback to This Version
                            </DropdownMenuItem>
                          </>
                        )}
                        {version.is_active && version.arm_status !== "eliminated" && (
                          <>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem
                              onClick={() => eliminateMutation.mutate(version.id)}
                              className="text-destructive"
                            >
                              <AlertTriangle className="mr-2 h-4 w-4" />
                              Eliminate from Testing
                            </DropdownMenuItem>
                          </>
                        )}
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>

      <Dialog open={!!selectedVersion} onOpenChange={() => setSelectedVersion(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>
              Prompt Version {selectedVersion?.version_number}
              {selectedVersion?.is_baseline && (
                <Badge variant="outline" className="ml-2">
                  Baseline
                </Badge>
              )}
            </DialogTitle>
            <DialogDescription>
              {selectedVersion?.change_summary || "No description provided"}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <h4 className="mb-2 text-sm font-medium">System Prompt</h4>
              <ScrollArea className="h-64 rounded-md border bg-muted/50 p-4">
                <pre className="whitespace-pre-wrap font-mono text-sm">
                  {selectedVersion?.system_prompt}
                </pre>
              </ScrollArea>
            </div>
            {selectedVersion?.initial_greeting && (
              <div>
                <h4 className="mb-2 text-sm font-medium">Initial Greeting</h4>
                <div className="rounded-md border bg-muted/50 p-4">
                  <p className="text-sm">{selectedVersion.initial_greeting}</p>
                </div>
              </div>
            )}
            <div className="flex gap-4 text-sm">
              <div>
                <span className="text-muted-foreground">Temperature:</span>{" "}
                <span className="font-medium">{selectedVersion?.temperature}</span>
              </div>
              <div>
                <span className="text-muted-foreground">Total Calls:</span>{" "}
                <span className="font-medium">
                  {selectedVersion ? formatNumber(selectedVersion.total_calls) : ""}
                </span>
              </div>
              <div>
                <span className="text-muted-foreground">Bookings:</span>{" "}
                <span className="font-medium">
                  {selectedVersion ? formatNumber(selectedVersion.booked_appointments) : ""}
                </span>
              </div>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
