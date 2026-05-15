"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { formatRelative } from "@/lib/utils/date";
import {
  Check,
  X,
  Eye,
  Wand2,
  MoreHorizontal,
  Lightbulb,
  ChevronDown,
  ChevronUp,
} from "lucide-react";

import {
  improvementSuggestionsApi,
  type ImprovementSuggestionResponse,
} from "@/lib/api/improvement-suggestions";
import { useWorkspaceId } from "@/hooks/use-workspace-id";
import { queryKeys } from "@/lib/query-keys";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { PageEmptyState, PageLoadingState } from "@/components/ui/page-state";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import { getApiErrorMessage } from "@/lib/utils/errors";

interface SuggestionsQueueProps {
  agentId?: string;
  statusFilter?: string;
  compact?: boolean;
}

export function SuggestionsQueue({
  agentId,
  statusFilter = "pending",
  compact = false,
}: SuggestionsQueueProps) {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();
  const [selectedSuggestion, setSelectedSuggestion] =
    useState<ImprovementSuggestionResponse | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [showRejectDialog, setShowRejectDialog] =
    useState<ImprovementSuggestionResponse | null>(null);

  const { data: suggestions, isPending } = useQuery({
    queryKey: queryKeys.improvementSuggestions.list(workspaceId ?? "", agentId, statusFilter),
    queryFn: () => {
      if (!workspaceId) throw new Error("No workspace");
      return improvementSuggestionsApi.list(workspaceId, {
        agent_id: agentId,
        status: statusFilter,
        page_size: 50,
      });
    },
    enabled: !!workspaceId,
  });

  const approveMutation = useMutation({
    mutationFn: (suggestionId: string) => {
      if (!workspaceId) throw new Error("No workspace");
      return improvementSuggestionsApi.approve(workspaceId, suggestionId);
    },
    onSuccess: () => {
      toast.success("Suggestion approved! New version created.");
      void queryClient.invalidateQueries({ queryKey: queryKeys.improvementSuggestions.root() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.agents.promptVersionsAll() });
    },
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Failed to approve suggestion")),
  });

  const rejectMutation = useMutation({
    mutationFn: ({ suggestionId, reason }: { suggestionId: string; reason?: string }) => {
      if (!workspaceId) throw new Error("No workspace");
      return improvementSuggestionsApi.reject(workspaceId, suggestionId, reason);
    },
    onSuccess: () => {
      toast.success("Suggestion rejected");
      void queryClient.invalidateQueries({ queryKey: queryKeys.improvementSuggestions.root() });
      setShowRejectDialog(null);
      setRejectReason("");
    },
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Failed to reject suggestion")),
  });

  const getMutationTypeBadge = (type: string) => {
    const colors: Record<string, string> = {
      warmer_tone: "bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200",
      more_concise: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
      add_urgency: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
      better_objections: "bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200",
      more_personalization: "bg-pink-100 text-pink-800 dark:bg-pink-900 dark:text-pink-200",
      clearer_value: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
      natural_flow: "bg-cyan-100 text-cyan-800 dark:bg-cyan-900 dark:text-cyan-200",
      trust_building: "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200",
    };

    const labels: Record<string, string> = {
      warmer_tone: "Warmer Tone",
      more_concise: "More Concise",
      add_urgency: "Add Urgency",
      better_objections: "Better Objections",
      more_personalization: "More Personal",
      clearer_value: "Clearer Value",
      natural_flow: "Natural Flow",
      trust_building: "Trust Building",
    };

    return (
      <Badge className={cn("text-xs", colors[type] || "bg-gray-100 text-gray-800")}>
        {labels[type] || type}
      </Badge>
    );
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "pending":
        return <Badge variant="outline">Pending</Badge>;
      case "approved":
        return (
          <Badge variant="default" className="bg-green-600">
            Approved
          </Badge>
        );
      case "rejected":
        return <Badge variant="destructive">Rejected</Badge>;
      default:
        return <Badge variant="secondary">{status}</Badge>;
    }
  };

  if (isPending) {
    return <PageLoadingState className="min-h-0 py-8" />;
  }

  if (!suggestions?.items.length) {
    return (
      <Card>
        <CardContent className="py-4">
          <PageEmptyState
            icon={<Lightbulb className="h-12 w-12" />}
            title="No Suggestions"
            description={
              statusFilter === "pending"
                ? "No pending improvement suggestions. Generate suggestions from an agent's A/B testing tab."
                : "No suggestions found with this filter."
            }
          />
        </CardContent>
      </Card>
    );
  }

  return (
    <>
      <div className="space-y-4">
        {suggestions.items.map((suggestion) => (
          <SuggestionCard
            key={suggestion.id}
            suggestion={suggestion}
            compact={compact}
            onApprove={() => approveMutation.mutate(suggestion.id)}
            onReject={() => setShowRejectDialog(suggestion)}
            onView={() => setSelectedSuggestion(suggestion)}
            getMutationTypeBadge={getMutationTypeBadge}
            getStatusBadge={getStatusBadge}
            isApproving={approveMutation.isPending}
          />
        ))}
      </div>

      {/* View Dialog */}
      <Dialog open={!!selectedSuggestion} onOpenChange={() => setSelectedSuggestion(null)}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Wand2 className="h-5 w-5" />
              AI Improvement Suggestion
              {selectedSuggestion && getMutationTypeBadge(selectedSuggestion.mutation_type)}
            </DialogTitle>
            <DialogDescription>{selectedSuggestion?.analysis_summary}</DialogDescription>
          </DialogHeader>

          {selectedSuggestion && (
            <div className="space-y-4">
              <div>
                <h4 className="mb-2 text-sm font-medium">Suggested Prompt</h4>
                <ScrollArea className="h-64 rounded-md border bg-muted/50 p-4">
                  <pre className="whitespace-pre-wrap font-mono text-sm">
                    {selectedSuggestion.suggested_prompt}
                  </pre>
                </ScrollArea>
              </div>

              {selectedSuggestion.suggested_greeting && (
                <div>
                  <h4 className="mb-2 text-sm font-medium">Suggested Greeting</h4>
                  <div className="rounded-md border bg-muted/50 p-4">
                    <p className="text-sm">{selectedSuggestion.suggested_greeting}</p>
                  </div>
                </div>
              )}

              {selectedSuggestion.expected_improvement && (
                <div>
                  <h4 className="mb-2 text-sm font-medium">Expected Improvement</h4>
                  <p className="text-sm text-muted-foreground">
                    {selectedSuggestion.expected_improvement}
                  </p>
                </div>
              )}
            </div>
          )}

          <DialogFooter>
            <Button variant="outline" onClick={() => setSelectedSuggestion(null)}>
              Close
            </Button>
            {selectedSuggestion?.status === "pending" && (
              <>
                <Button
                  variant="destructive"
                  onClick={() => {
                    setShowRejectDialog(selectedSuggestion);
                    setSelectedSuggestion(null);
                  }}
                >
                  Reject
                </Button>
                <Button
                  onClick={() => {
                    approveMutation.mutate(selectedSuggestion.id);
                    setSelectedSuggestion(null);
                  }}
                  disabled={approveMutation.isPending}
                >
                  <Check className="mr-2 h-4 w-4" />
                  Approve & Activate
                </Button>
              </>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Reject Dialog */}
      <Dialog open={!!showRejectDialog} onOpenChange={() => setShowRejectDialog(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Reject Suggestion</DialogTitle>
            <DialogDescription>
              Optionally provide a reason for rejecting this suggestion.
            </DialogDescription>
          </DialogHeader>
          <Textarea
            placeholder="Reason for rejection (optional)"
            value={rejectReason}
            onChange={(e) => setRejectReason(e.target.value)}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowRejectDialog(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() =>
                showRejectDialog &&
                rejectMutation.mutate({
                  suggestionId: showRejectDialog.id,
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
    </>
  );
}

interface SuggestionCardProps {
  suggestion: ImprovementSuggestionResponse;
  compact: boolean;
  onApprove: () => void;
  onReject: () => void;
  onView: () => void;
  getMutationTypeBadge: (type: string) => React.ReactNode;
  getStatusBadge: (status: string) => React.ReactNode;
  isApproving: boolean;
}

function SuggestionCard({
  suggestion,
  compact,
  onApprove,
  onReject,
  onView,
  getMutationTypeBadge,
  getStatusBadge,
  isApproving,
}: SuggestionCardProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <CardTitle className="text-base">
                <Wand2 className="mr-2 inline h-4 w-4" />
                AI Suggestion
              </CardTitle>
              {getMutationTypeBadge(suggestion.mutation_type)}
              {getStatusBadge(suggestion.status)}
            </div>
            <CardDescription className="line-clamp-2">
              {suggestion.analysis_summary}
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            {suggestion.status === "pending" && (
              <>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={onReject}
                  className="text-destructive"
                >
                  <X className="h-4 w-4" />
                </Button>
                <Button size="sm" onClick={onApprove} disabled={isApproving}>
                  <Check className="h-4 w-4" />
                </Button>
              </>
            )}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon" className="h-8 w-8">
                  <MoreHorizontal className="h-4 w-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={onView}>
                  <Eye className="mr-2 h-4 w-4" />
                  View Full Prompt
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
      </CardHeader>

      {!compact && (
        <CardContent className="pt-2">
          <Collapsible open={isExpanded} onOpenChange={setIsExpanded}>
            <CollapsibleTrigger asChild>
              <Button variant="ghost" size="sm" className="w-full justify-between">
                <span className="text-xs text-muted-foreground">
                  {isExpanded ? "Hide preview" : "Show preview"}
                </span>
                {isExpanded ? (
                  <ChevronUp className="h-4 w-4" />
                ) : (
                  <ChevronDown className="h-4 w-4" />
                )}
              </Button>
            </CollapsibleTrigger>
            <CollapsibleContent>
              <div className="mt-2 rounded-md border bg-muted/50 p-3">
                <pre className="line-clamp-10 whitespace-pre-wrap font-mono text-xs">
                  {suggestion.suggested_prompt}
                </pre>
              </div>
            </CollapsibleContent>
          </Collapsible>

          <div className="mt-3 flex items-center justify-between text-xs text-muted-foreground">
            <span>
              Created{" "}
              {formatRelative(suggestion.created_at)}
            </span>
            {suggestion.expected_improvement && (
              <span className="max-w-xs truncate">
                Expected: {suggestion.expected_improvement}
              </span>
            )}
          </div>
        </CardContent>
      )}
    </Card>
  );
}
