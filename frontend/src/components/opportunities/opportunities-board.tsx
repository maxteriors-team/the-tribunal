"use client";

import {
  DndContext,
  DragOverlay,
  PointerSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KanbanSquare, MoreVertical } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  PageEmptyState,
  PageErrorState,
  PageLoadingState,
} from "@/components/ui/page-state";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { opportunitiesApi } from "@/lib/api/opportunities";
import { queryKeys } from "@/lib/query-keys";
import { cn } from "@/lib/utils";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { formatCurrency } from "@/lib/utils/number";
import type { Opportunity, Pipeline, PipelineStage } from "@/types";

import { OpportunityDetailSheet } from "./opportunity-detail-sheet";

const BOARD_PAGE_SIZE = 200;

const STAGE_ACCENT: Record<string, string> = {
  active: "bg-blue-500",
  won: "bg-green-500",
  lost: "bg-red-500",
};

export function OpportunitiesBoard() {
  const workspaceId = useWorkspaceId();

  const {
    data: pipelines,
    isPending: pipelinesPending,
    isError: pipelinesError,
    refetch: refetchPipelines,
  } = useQuery({
    queryKey: queryKeys.opportunities.pipelines(workspaceId ?? ""),
    queryFn: () => opportunitiesApi.listPipelines(workspaceId!),
    enabled: !!workspaceId,
  });

  // The promotion flow uses the earliest active pipeline; mirror that here.
  const defaultPipeline = useMemo<Pipeline | undefined>(() => {
    if (!pipelines || pipelines.length === 0) return undefined;
    return [...pipelines].sort(
      (a, b) =>
        new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
    )[0];
  }, [pipelines]);

  if (!workspaceId || pipelinesPending) {
    return <PageLoadingState message="Loading pipeline…" />;
  }

  if (pipelinesError) {
    return (
      <PageErrorState
        message="Couldn't load pipelines."
        onRetry={() => void refetchPipelines()}
      />
    );
  }

  if (!defaultPipeline) {
    return (
      <PageEmptyState
        icon={<KanbanSquare className="h-10 w-10" />}
        title="No pipeline yet"
        description="This workspace has no active pipeline. Create one to start tracking opportunities."
      />
    );
  }

  return <PipelineBoard workspaceId={workspaceId} pipeline={defaultPipeline} />;
}

function PipelineBoard({
  workspaceId,
  pipeline,
}: {
  workspaceId: string;
  pipeline: Pipeline;
}) {
  const queryClient = useQueryClient();
  const [activeId, setActiveId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);

  const sensors = useSensors(
    // Require a small drag distance so a plain click still opens the card.
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } })
  );

  const stages = useMemo<PipelineStage[]>(
    () => [...pipeline.stages].sort((a, b) => a.order - b.order),
    [pipeline.stages]
  );

  const listParams = { pipeline_id: pipeline.id };
  const listKey = queryKeys.opportunities.list(workspaceId, listParams);

  const {
    data,
    isPending,
    isError,
    refetch,
  } = useQuery({
    queryKey: listKey,
    queryFn: () =>
      opportunitiesApi.list(workspaceId, {
        ...listParams,
        page_size: BOARD_PAGE_SIZE,
      }),
    enabled: !!workspaceId,
  });

  const moveMutation = useMutation({
    mutationFn: ({ opportunityId, stageId }: { opportunityId: string; stageId: string }) =>
      opportunitiesApi.update(workspaceId, opportunityId, { stage_id: stageId }),
    onMutate: async ({ opportunityId, stageId }) => {
      await queryClient.cancelQueries({ queryKey: listKey });
      const previous = queryClient.getQueryData<{ items: Opportunity[] }>(listKey);
      const stage = stages.find((s) => s.id === stageId);
      queryClient.setQueryData<typeof previous>(listKey, (current) => {
        if (!current) return current;
        return {
          ...current,
          items: current.items.map((opp) =>
            opp.id === opportunityId
              ? {
                  ...opp,
                  stage_id: stageId,
                  probability: stage?.probability ?? opp.probability,
                }
              : opp
          ),
        };
      });
      return { previous };
    },
    onError: (err, _vars, context) => {
      if (context?.previous) {
        queryClient.setQueryData(listKey, context.previous);
      }
      toast.error(getApiErrorMessage(err, "Failed to move opportunity"));
    },
    onSuccess: (_data, { stageId }) => {
      const stageName = stages.find((s) => s.id === stageId)?.name ?? "stage";
      toast.success(`Moved to ${stageName}`);
    },
    onSettled: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.opportunities.all(workspaceId),
      });
    },
  });

  const opportunities = useMemo(() => data?.items ?? [], [data]);
  const byStage = useMemo(() => {
    const map = new Map<string, Opportunity[]>();
    for (const stage of stages) map.set(stage.id, []);
    for (const opp of opportunities) {
      if (opp.stage_id && map.has(opp.stage_id)) {
        map.get(opp.stage_id)!.push(opp);
      }
    }
    return map;
  }, [opportunities, stages]);

  const activeOpportunity = activeId
    ? opportunities.find((o) => o.id === activeId)
    : undefined;

  function handleDragStart(event: DragStartEvent) {
    setActiveId(String(event.active.id));
  }

  function handleDragEnd(event: DragEndEvent) {
    setActiveId(null);
    const { active, over } = event;
    if (!over) return;
    const opportunityId = String(active.id);
    const targetStageId = String(over.id);
    const opp = opportunities.find((o) => o.id === opportunityId);
    if (!opp || opp.stage_id === targetStageId) return;
    moveMutation.mutate({ opportunityId, stageId: targetStageId });
  }

  function openDetail(opportunityId: string) {
    setSelectedId(opportunityId);
    setDetailOpen(true);
  }

  if (isPending) {
    return <PageLoadingState message="Loading opportunities…" />;
  }

  if (isError) {
    return (
      <PageErrorState
        message="Couldn't load opportunities."
        onRetry={() => void refetch()}
      />
    );
  }

  return (
    <>
      <DndContext
        sensors={sensors}
        onDragStart={handleDragStart}
        onDragEnd={handleDragEnd}
      >
        <div className="flex h-full gap-4 overflow-x-auto pb-4">
          {stages.map((stage) => (
            <StageColumn
              key={stage.id}
              stage={stage}
              stages={stages}
              opportunities={byStage.get(stage.id) ?? []}
              onOpen={openDetail}
              onMove={(opportunityId, stageId) =>
                moveMutation.mutate({ opportunityId, stageId })
              }
            />
          ))}
        </div>

        <DragOverlay>
          {activeOpportunity ? (
            <OpportunityCardBody opportunity={activeOpportunity} dragging />
          ) : null}
        </DragOverlay>
      </DndContext>

      <OpportunityDetailSheet
        workspaceId={workspaceId}
        opportunityId={selectedId}
        stages={stages}
        open={detailOpen}
        onOpenChange={setDetailOpen}
      />
    </>
  );
}

function StageColumn({
  stage,
  stages,
  opportunities,
  onOpen,
  onMove,
}: {
  stage: PipelineStage;
  stages: PipelineStage[];
  opportunities: Opportunity[];
  onOpen: (opportunityId: string) => void;
  onMove: (opportunityId: string, stageId: string) => void;
}) {
  const { setNodeRef, isOver } = useDroppable({ id: stage.id });

  return (
    <div
      ref={setNodeRef}
      data-testid={`stage-column-${stage.id}`}
      className={cn(
        "flex w-72 shrink-0 flex-col rounded-lg border bg-muted/30",
        isOver && "ring-2 ring-primary"
      )}
    >
      <div className="flex items-center justify-between gap-2 border-b px-3 py-2.5">
        <div className="flex items-center gap-2">
          <span
            className={cn(
              "h-2.5 w-2.5 rounded-full",
              STAGE_ACCENT[stage.stage_type] ?? "bg-muted-foreground"
            )}
          />
          <span className="text-sm font-medium">{stage.name}</span>
        </div>
        <Badge variant="secondary" className="text-xs">
          {opportunities.length}
        </Badge>
      </div>

      <div className="flex flex-1 flex-col gap-2 overflow-y-auto p-2">
        {opportunities.length === 0 ? (
          <p className="px-2 py-6 text-center text-xs text-muted-foreground">
            No opportunities
          </p>
        ) : (
          opportunities.map((opportunity) => (
            <OpportunityCard
              key={opportunity.id}
              opportunity={opportunity}
              stages={stages}
              onOpen={onOpen}
              onMove={onMove}
            />
          ))
        )}
      </div>
    </div>
  );
}

function OpportunityCard({
  opportunity,
  stages,
  onOpen,
  onMove,
}: {
  opportunity: Opportunity;
  stages: PipelineStage[];
  onOpen: (opportunityId: string) => void;
  onMove: (opportunityId: string, stageId: string) => void;
}) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: opportunity.id,
  });

  return (
    <div
      ref={setNodeRef}
      className={cn("relative", isDragging && "opacity-50")}
      data-testid={`opportunity-card-${opportunity.id}`}
    >
      <button
        type="button"
        className="w-full cursor-pointer text-left"
        onClick={() => onOpen(opportunity.id)}
        {...attributes}
        {...listeners}
      >
        <OpportunityCardBody opportunity={opportunity} />
      </button>

      <div className="absolute right-1.5 top-1.5">
        <DropdownMenu>
          <DropdownMenuTrigger
            className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
            aria-label="Opportunity actions"
            onClick={(e) => e.stopPropagation()}
          >
            <MoreVertical className="h-4 w-4" />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuLabel>Move to</DropdownMenuLabel>
            <DropdownMenuSeparator />
            {stages
              .filter((s) => s.id !== opportunity.stage_id)
              .map((stage) => (
                <DropdownMenuItem
                  key={stage.id}
                  onClick={() => onMove(opportunity.id, stage.id)}
                >
                  {stage.name}
                </DropdownMenuItem>
              ))}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  );
}

function OpportunityCardBody({
  opportunity,
  dragging,
}: {
  opportunity: Opportunity;
  dragging?: boolean;
}) {
  return (
    <div
      className={cn(
        "rounded-md border bg-background p-3 pr-7 shadow-sm transition-colors hover:border-primary/50",
        dragging && "w-64 shadow-md"
      )}
    >
      <p className="line-clamp-2 text-sm font-medium">{opportunity.name}</p>
      <div className="mt-2 flex items-center justify-between text-xs text-muted-foreground">
        <span>{opportunity.probability}%</span>
        {opportunity.amount != null ? (
          <span className="font-medium text-foreground">
            {formatCurrency(opportunity.amount, opportunity.currency)}
          </span>
        ) : null}
      </div>
    </div>
  );
}
