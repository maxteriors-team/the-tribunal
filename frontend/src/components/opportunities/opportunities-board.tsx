"use client";

import {
  DndContext,
  DragOverlay,
  PointerSensor,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KanbanSquare, Plus, Settings2 } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { OutboundCallDialog } from "@/components/calls/outbound-call-dialog";
import { ScheduleAppointmentDialog } from "@/components/contacts/schedule-appointment-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  PageEmptyState,
  PageErrorState,
  PageLoadingState,
} from "@/components/ui/page-state";
import { useContact } from "@/hooks/useContacts";
import { useOutboundCall } from "@/hooks/useOutboundCall";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { opportunitiesApi } from "@/lib/api/opportunities";
import { queryKeys } from "@/lib/query-keys";
import { cn } from "@/lib/utils";
import { getApiErrorMessage } from "@/lib/utils/errors";
import type { Opportunity, Pipeline, PipelineStage } from "@/types";

import { ManageStagesDialog } from "./manage-stages-dialog";
import { OpportunityCard, OpportunityCardSummary } from "./opportunity-card";
import { OpportunityCreateSheet } from "./opportunity-create-sheet";
import { OpportunityDetailSheet } from "./opportunity-detail-sheet";

const BOARD_PAGE_SIZE = 200;

/**
 * The board renders a lead's name, phone, and lifecycle status straight from
 * the list payload, so a stale card would offer to dial a number the contact no
 * longer uses. Keep it fresh on focus/mount rather than trusting cache age.
 */
const BOARD_STALE_TIME_MS = 30_000;

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
  const [createOpen, setCreateOpen] = useState(false);
  const [createStageId, setCreateStageId] = useState<string | undefined>(undefined);
  const [manageStagesOpen, setManageStagesOpen] = useState(false);
  const [scheduleContactId, setScheduleContactId] = useState<number | null>(null);

  const {
    callTarget,
    callDialogOpen,
    setCallDialogOpen,
    startCall,
    submitCall,
    initiateCallMutation,
  } = useOutboundCall(workspaceId);

  // The board payload carries only a contact summary; the appointment dialog
  // needs the full record, so fetch it once the operator asks to book.
  const { data: scheduleContact } = useContact(
    workspaceId,
    scheduleContactId ?? undefined,
  );

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
    staleTime: BOARD_STALE_TIME_MS,
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

  function openCreate(stageId?: string) {
    setCreateStageId(stageId);
    setCreateOpen(true);
  }

  function callContact(opportunity: Opportunity) {
    const contact = opportunity.primary_contact;
    if (!contact) return;
    startCall({ name: contact.full_name, phone: contact.phone_number });
  }

  function scheduleContactFor(opportunity: Opportunity) {
    const contact = opportunity.primary_contact;
    if (!contact) return;
    setScheduleContactId(contact.id);
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
      <div className="flex h-full flex-col gap-4">
        <div className="flex items-center justify-between gap-2">
          <span className="text-sm font-medium text-muted-foreground">
            {pipeline.name}
          </span>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={() => setManageStagesOpen(true)}
              data-testid="manage-stages"
            >
              <Settings2 className="mr-1.5 h-4 w-4" />
              Manage stages
            </Button>
            <Button size="sm" onClick={() => openCreate()} data-testid="add-opportunity">
              <Plus className="mr-1.5 h-4 w-4" />
              Add Opportunity
            </Button>
          </div>
        </div>

        <DndContext
          sensors={sensors}
          onDragStart={handleDragStart}
          onDragEnd={handleDragEnd}
        >
          <div className="flex flex-1 gap-4 overflow-x-auto pb-4">
            {stages.map((stage) => (
              <StageColumn
                key={stage.id}
                stage={stage}
                stages={stages}
                opportunities={byStage.get(stage.id) ?? []}
                onOpen={openDetail}
                onAdd={() => openCreate(stage.id)}
                onMove={(opportunityId, stageId) =>
                  moveMutation.mutate({ opportunityId, stageId })
                }
                onCall={callContact}
                onSchedule={scheduleContactFor}
              />
            ))}
          </div>

          <DragOverlay>
            {activeOpportunity ? (
              <OpportunityCardSummary opportunity={activeOpportunity} dragging />
            ) : null}
          </DragOverlay>
        </DndContext>
      </div>

      <OpportunityDetailSheet
        workspaceId={workspaceId}
        opportunityId={selectedId}
        stages={stages}
        open={detailOpen}
        onOpenChange={setDetailOpen}
      />

      <OpportunityCreateSheet
        workspaceId={workspaceId}
        pipelineId={pipeline.id}
        stages={stages}
        defaultStageId={createStageId}
        open={createOpen}
        onOpenChange={setCreateOpen}
      />

      <ManageStagesDialog
        workspaceId={workspaceId}
        pipeline={pipeline}
        open={manageStagesOpen}
        onOpenChange={setManageStagesOpen}
      />

      <OutboundCallDialog
        open={callDialogOpen}
        onOpenChange={setCallDialogOpen}
        workspaceId={workspaceId}
        contactName={callTarget?.name}
        contactPhone={callTarget?.phone}
        onSubmit={submitCall}
        isSubmitting={initiateCallMutation.isPending}
      />

      {scheduleContact ? (
        <ScheduleAppointmentDialog
          contact={scheduleContact}
          open={!!scheduleContactId}
          onOpenChange={(open) => {
            if (!open) setScheduleContactId(null);
          }}
        />
      ) : null}
    </>
  );
}

function StageColumn({
  stage,
  stages,
  opportunities,
  onOpen,
  onAdd,
  onMove,
  onCall,
  onSchedule,
}: {
  stage: PipelineStage;
  stages: PipelineStage[];
  opportunities: Opportunity[];
  onOpen: (opportunityId: string) => void;
  onAdd: () => void;
  onMove: (opportunityId: string, stageId: string) => void;
  onCall: (opportunity: Opportunity) => void;
  onSchedule: (opportunity: Opportunity) => void;
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
          <div className="flex flex-col items-center gap-2 px-2 py-6 text-center">
            <p className="text-xs text-muted-foreground">No opportunities</p>
            <Button
              variant="ghost"
              size="sm"
              className="text-xs text-muted-foreground"
              onClick={onAdd}
              data-testid={`add-opportunity-${stage.id}`}
            >
              <Plus className="mr-1 h-3.5 w-3.5" />
              Add deal
            </Button>
          </div>
        ) : (
          opportunities.map((opportunity) => (
            <OpportunityCard
              key={opportunity.id}
              opportunity={opportunity}
              stages={stages}
              onOpen={onOpen}
              onMove={onMove}
              onCall={onCall}
              onSchedule={onSchedule}
            />
          ))
        )}
      </div>
    </div>
  );
}

