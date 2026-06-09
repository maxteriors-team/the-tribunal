"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import {
  PageErrorState,
  PageLoadingState,
} from "@/components/ui/page-state";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { opportunitiesApi } from "@/lib/api/opportunities";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { formatCurrency } from "@/lib/utils/number";
import type { PipelineStage } from "@/types";

interface OpportunityDetailSheetProps {
  workspaceId: string;
  opportunityId: string | null;
  stages: PipelineStage[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function OpportunityDetailSheet({
  workspaceId,
  opportunityId,
  stages,
  open,
  onOpenChange,
}: OpportunityDetailSheetProps) {
  const queryClient = useQueryClient();

  const {
    data: opportunity,
    isPending,
    isError,
    refetch,
  } = useQuery({
    queryKey: queryKeys.opportunities.detail(workspaceId, opportunityId ?? ""),
    queryFn: () => opportunitiesApi.get(workspaceId, opportunityId!),
    enabled: open && !!workspaceId && !!opportunityId,
  });

  const moveMutation = useMutation({
    mutationFn: (stageId: string) =>
      opportunitiesApi.update(workspaceId, opportunityId!, { stage_id: stageId }),
    onSuccess: (updated) => {
      const stageName =
        stages.find((s) => s.id === updated.stage_id)?.name ?? "stage";
      toast.success(`Moved to ${stageName}`);
      void queryClient.invalidateQueries({
        queryKey: queryKeys.opportunities.all(workspaceId),
      });
    },
    onError: (err: unknown) =>
      toast.error(getApiErrorMessage(err, "Failed to move opportunity")),
  });

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="flex w-full flex-col gap-0 overflow-y-auto sm:max-w-md">
        <SheetHeader>
          <SheetTitle>{opportunity?.name ?? "Opportunity"}</SheetTitle>
          <SheetDescription>
            View and move this opportunity between pipeline stages.
          </SheetDescription>
        </SheetHeader>

        <div className="space-y-6 px-4 pb-6">
          {isPending ? (
            <PageLoadingState message="Loading opportunity…" />
          ) : isError || !opportunity ? (
            <PageErrorState
              message="Couldn't load this opportunity."
              onRetry={() => void refetch()}
            />
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="outline" className="capitalize">
                  {opportunity.status}
                </Badge>
                <Badge variant="secondary">
                  {opportunity.probability}% probability
                </Badge>
                {opportunity.source ? (
                  <Badge variant="outline">{opportunity.source}</Badge>
                ) : null}
              </div>

              <div className="space-y-1.5">
                <p className="text-sm font-medium">Stage</p>
                <Select
                  value={opportunity.stage_id ?? undefined}
                  onValueChange={(value) => moveMutation.mutate(value)}
                  disabled={moveMutation.isPending}
                >
                  <SelectTrigger
                    className="w-full"
                    data-testid="opportunity-stage-select"
                  >
                    <SelectValue placeholder="Select a stage" />
                  </SelectTrigger>
                  <SelectContent>
                    {stages.map((stage) => (
                      <SelectItem key={stage.id} value={stage.id}>
                        {stage.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {opportunity.amount != null ? (
                <div className="space-y-1">
                  <p className="text-sm font-medium">Amount</p>
                  <p className="text-sm text-muted-foreground">
                    {formatCurrency(opportunity.amount, opportunity.currency)}
                  </p>
                </div>
              ) : null}

              {opportunity.description ? (
                <div className="space-y-1">
                  <p className="text-sm font-medium">Description</p>
                  <p className="whitespace-pre-wrap text-sm text-muted-foreground">
                    {opportunity.description}
                  </p>
                </div>
              ) : null}

              {opportunity.activities && opportunity.activities.length > 0 ? (
                <div className="space-y-2">
                  <p className="text-sm font-medium">Activity</p>
                  <ul className="space-y-2">
                    {opportunity.activities.map((activity) => (
                      <li
                        key={activity.id}
                        className="rounded-md border p-2 text-xs text-muted-foreground"
                      >
                        <span className="font-medium text-foreground">
                          {activity.activity_type.replace("_", " ")}
                        </span>
                        {activity.description ? ` — ${activity.description}` : null}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
