"use client";

import {
  DndContext,
  DragOverlay,
  closestCorners,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragStartEvent,
  type DragEndEvent,
  type DragOverEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { GripVertical, DollarSign, Calendar, CircleDot } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { ScrollArea, ScrollBar } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { opportunitiesApi } from "@/lib/api/opportunities";
import { queryKeys } from "@/lib/query-keys";
import { opportunityStatusColors } from "@/lib/status-colors";
import { cn } from "@/lib/utils";
import { formatDate } from "@/lib/utils/date";
import type { Opportunity, OpportunityStatus, PipelineStage } from "@/types";

import { OpportunityDetailSheet } from "./opportunity-detail-sheet";


interface OpportunitiesBoardProps {
  workspaceId: string;
}

function formatCurrency(amount: number | undefined, currency: string) {
  if (!amount) return "$0";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: currency,
    notation: "compact",
  }).format(amount);
}


interface SortableOpportunityCardProps {
  opportunity: Opportunity;
  stage: PipelineStage;
  onClick: () => void;
}

function SortableOpportunityCard({
  opportunity,
  stage,
  onClick,
}: SortableOpportunityCardProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({
    id: opportunity.id,
    data: {
      type: "opportunity",
      opportunity,
      stageId: stage.id,
    },
  });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  };

  return (
    <Card
      ref={setNodeRef}
      style={style}
      className={cn(
        "bg-background hover:shadow-md transition-all cursor-pointer group",
        isDragging && "opacity-50 shadow-lg ring-2 ring-primary"
      )}
      onClick={onClick}
    >
      <CardContent className="p-3 space-y-2">
        <div className="flex items-start gap-2">
          <button
            className="mt-1 cursor-grab active:cursor-grabbing opacity-0 group-hover:opacity-100 transition-opacity touch-none"
            {...attributes}
            {...listeners}
          >
            <GripVertical className="h-4 w-4 text-muted-foreground" />
          </button>
          <div className="flex-1 min-w-0">
            <div className="flex items-start justify-between gap-2">
              <p className="text-sm font-medium line-clamp-2">{opportunity.name}</p>
              <Badge
                variant="outline"
                className={cn("text-xs flex-shrink-0", opportunityStatusColors[opportunity.status as OpportunityStatus] ?? "bg-info/10 text-info border-info/20")}
              >
                {opportunity.status}
              </Badge>
            </div>
            <div className="flex items-center gap-2 mt-2">
              {opportunity.amount && (
                <div className="flex items-center gap-1 text-sm text-muted-foreground">
                  <DollarSign className="h-3 w-3" />
                  {formatCurrency(opportunity.amount, opportunity.currency)}
                </div>
              )}
              <Badge variant="secondary" className="text-xs">
                {stage.probability}%
              </Badge>
            </div>
            {opportunity.expected_close_date && (
              <div className="flex items-center gap-1 text-xs text-muted-foreground mt-1">
                <Calendar className="h-3 w-3" />
                {formatDate(opportunity.expected_close_date)}
              </div>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function OpportunityCardOverlay({ opportunity }: { opportunity: Opportunity }) {
  return (
    <Card className="bg-background shadow-xl ring-2 ring-primary w-full max-w-[280px]">
      <CardContent className="p-3 space-y-2">
        <p className="text-sm font-medium line-clamp-2">{opportunity.name}</p>
        {opportunity.amount && (
          <p className="text-sm text-muted-foreground">
            {formatCurrency(opportunity.amount, opportunity.currency)}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

interface StageColumnProps {
  stage: PipelineStage;
  opportunities: Opportunity[];
  totalValue: number;
  onOpportunityClick: (opportunity: Opportunity) => void;
}

function StageColumn({
  stage,
  opportunities,
  totalValue,
  onOpportunityClick,
}: StageColumnProps) {
  const { setNodeRef } = useSortable({
    id: `stage-${stage.id}`,
    data: {
      type: "stage",
      stage,
    },
  });

  return (
    <div
      ref={setNodeRef}
      className="bg-muted/30 rounded-lg p-3 min-h-[200px] flex flex-col"
    >
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <CircleDot
            className={cn(
              "h-3 w-3",
              stage.stage_type === "won" && "text-success",
              stage.stage_type === "lost" && "text-destructive",
              stage.stage_type === "active" && "text-info"
            )}
          />
          <h3 className="text-sm font-medium">{stage.name}</h3>
        </div>
        <Badge variant="outline" className="text-xs">
          {opportunities.length}
        </Badge>
      </div>
      <div className="text-xs text-muted-foreground mb-3">
        {formatCurrency(totalValue, "USD")}
      </div>
      <SortableContext
        items={opportunities.map((o) => o.id)}
        strategy={verticalListSortingStrategy}
      >
        <div className="space-y-2 flex-1">
          {opportunities.map((opportunity) => (
            <SortableOpportunityCard
              key={opportunity.id}
              opportunity={opportunity}
              stage={stage}
              onClick={() => onOpportunityClick(opportunity)}
            />
          ))}
          {opportunities.length === 0 && (
            <div className="text-center py-8 border-2 border-dashed border-muted rounded-lg">
              <p className="text-xs text-muted-foreground">Drop here</p>
            </div>
          )}
        </div>
      </SortableContext>
    </div>
  );
}

export function OpportunitiesBoard({ workspaceId }: OpportunitiesBoardProps) {
  const queryClient = useQueryClient();
  const [activeOpportunity, setActiveOpportunity] = useState<Opportunity | null>(null);
  const [selectedOpportunity, setSelectedOpportunity] = useState<Opportunity | null>(null);
  const [detailSheetOpen, setDetailSheetOpen] = useState(false);

  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 8,
      },
    }),
    useSensor(KeyboardSensor)
  );

  const { data: pipelines, isPending: pipelinesLoading } = useQuery({
    queryKey: queryKeys.opportunities.pipelines(workspaceId ?? ""),
    queryFn: () => opportunitiesApi.listPipelines(workspaceId),
    enabled: !!workspaceId,
  });

  const { data: opportunities, isPending: opportunitiesLoading } = useQuery({
    queryKey: queryKeys.opportunities.all(workspaceId ?? ""),
    queryFn: () => opportunitiesApi.list(workspaceId, { page_size: 500 }),
    enabled: !!workspaceId,
  });

  const updateMutation = useMutation({
    mutationFn: ({
      opportunityId,
      stageId,
    }: {
      opportunityId: string;
      stageId: string;
    }) => opportunitiesApi.update(workspaceId, opportunityId, { stage_id: stageId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.opportunities.all(workspaceId ?? "") });
    },
  });

  const handleDragStart = (event: DragStartEvent) => {
    const { active } = event;
    const activeData = active.data.current;
    if (activeData?.type === "opportunity") {
      setActiveOpportunity(activeData.opportunity);
    }
  };

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    setActiveOpportunity(null);

    if (!over) return;

    const activeData = active.data.current;
    const overData = over.data.current;

    if (activeData?.type !== "opportunity") return;

    // Determine target stage
    let targetStageId: string | null = null;

    if (overData?.type === "stage") {
      targetStageId = overData.stage.id;
    } else if (overData?.type === "opportunity") {
      targetStageId = overData.stageId;
    } else if (over.id.toString().startsWith("stage-")) {
      targetStageId = over.id.toString().replace("stage-", "");
    }

    if (!targetStageId) return;

    const opportunity = activeData.opportunity as Opportunity;
    if (opportunity.stage_id === targetStageId) return;

    // Update opportunity stage
    updateMutation.mutate({
      opportunityId: opportunity.id,
      stageId: targetStageId,
    });
  };

  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const handleDragOver = (_event: DragOverEvent) => {
    // Optional: Add visual feedback during drag over
  };

  const handleOpportunityClick = (opportunity: Opportunity) => {
    setSelectedOpportunity(opportunity);
    setDetailSheetOpen(true);
  };

  if (pipelinesLoading || opportunitiesLoading) {
    return (
      <div className="w-full h-full p-4">
        <div className="flex gap-4 overflow-x-auto">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="min-w-[300px]">
              <Skeleton className="h-10 w-full mb-4" />
              <div className="space-y-2">
                {Array.from({ length: 3 }).map((_, j) => (
                  <Skeleton key={j} className="h-24 w-full" />
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (!pipelines || pipelines.length === 0) {
    return (
      <div className="w-full h-full flex items-center justify-center">
        <p className="text-muted-foreground">
          No pipelines found. Create one to get started.
        </p>
      </div>
    );
  }

  const opportunitiesByStage = (stageId: string) => {
    return (opportunities?.items || []).filter((opp) => opp.stage_id === stageId);
  };

  return (
    <>
      <DndContext
        sensors={sensors}
        collisionDetection={closestCorners}
        onDragStart={handleDragStart}
        onDragEnd={handleDragEnd}
        onDragOver={handleDragOver}
      >
        <ScrollArea className="w-full h-full">
          <div className="p-4 flex gap-6">
            {pipelines.map((pipeline) => (
              <div key={pipeline.id} className="min-w-[320px]">
                <h2 className="font-semibold mb-4 text-sm px-2">{pipeline.name}</h2>
                <div className="space-y-3">
                  {pipeline.stages
                    .sort((a, b) => a.order - b.order)
                    .map((stage) => {
                      const stageOpps = opportunitiesByStage(stage.id);
                      const totalValue = stageOpps.reduce(
                        (sum, opp) => sum + (opp.amount || 0),
                        0
                      );

                      return (
                        <StageColumn
                          key={stage.id}
                          stage={stage}
                          opportunities={stageOpps}
                          totalValue={totalValue}
                          onOpportunityClick={handleOpportunityClick}
                        />
                      );
                    })}
                </div>
              </div>
            ))}
          </div>
          <ScrollBar orientation="horizontal" />
        </ScrollArea>

        <DragOverlay>
          {activeOpportunity && (
            <OpportunityCardOverlay opportunity={activeOpportunity} />
          )}
        </DragOverlay>
      </DndContext>

      <OpportunityDetailSheet
        open={detailSheetOpen}
        onOpenChange={setDetailSheetOpen}
        opportunity={selectedOpportunity}
        workspaceId={workspaceId}
      />
    </>
  );
}
