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
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KanbanSquare, Plus, Settings2 } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { OutboundCallDialog } from "@/components/calls/outbound-call-dialog";
import { ScheduleAppointmentDialog } from "@/components/contacts/schedule-appointment-dialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ContactPicker } from "@/components/ui/contact-combobox";
import { HorizontalScroll } from "@/components/ui/horizontal-scroll";
import { Label } from "@/components/ui/label";
import { PageEmptyState, PageErrorState, PageLoadingState } from "@/components/ui/page-state";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useContact } from "@/hooks/useContacts";
import { useOutboundCall } from "@/hooks/useOutboundCall";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { opportunitiesApi } from "@/lib/api/opportunities";
import { settingsApi } from "@/lib/api/settings";
import { queryKeys } from "@/lib/query-keys";
import { cn } from "@/lib/utils";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { useWorkspace } from "@/providers/workspace-provider";
import type { Contact, Opportunity, Pipeline, PipelineStage } from "@/types";

import { ManageStagesDialog } from "./manage-stages-dialog";
import { OpportunityCard, OpportunityCardSummary } from "./opportunity-card";
import { OpportunityCreateSheet } from "./opportunity-create-sheet";
import { OpportunityDetailSheet } from "./opportunity-detail-sheet";

const BOARD_PAGE_SIZE = 200;

/** Sentinel for "no rep filter"; Radix Select cannot hold an empty-string value. */
const ALL_REPS_VALUE = "all";

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
      (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
    )[0];
  }, [pipelines]);

  if (!workspaceId || pipelinesPending) {
    return <PageLoadingState message="Loading pipeline…" />;
  }

  if (pipelinesError) {
    return (
      <PageErrorState message="Couldn't load pipelines." onRetry={() => void refetchPipelines()} />
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

function PipelineBoard({ workspaceId, pipeline }: { workspaceId: string; pipeline: Pipeline }) {
  const queryClient = useQueryClient();
  const { currentWorkspace } = useWorkspace();
  const canAssignOwners = currentWorkspace?.role !== "sales_rep";
  const [activeId, setActiveId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [createStageId, setCreateStageId] = useState<string | undefined>(undefined);
  const [manageStagesOpen, setManageStagesOpen] = useState(false);
  const [scheduleContactId, setScheduleContactId] = useState<number | null>(null);
  const [pendingRemoval, setPendingRemoval] = useState<Opportunity | null>(null);
  const [customerFilter, setCustomerFilter] = useState<{
    id: string;
    contact: Contact | null;
  }>({ id: "", contact: null });
  const [repFilter, setRepFilter] = useState<string>(ALL_REPS_VALUE);

  // A sales rep only ever sees their own deals, so a rep filter would be a
  // single-option no-op for them. Reuses the picker's key, so the team list is
  // fetched once and shared with the owner picker in the detail sheet.
  const repsQuery = useQuery({
    queryKey: queryKeys.settings.activeTeam(workspaceId),
    queryFn: () => settingsApi.getActiveTeamMembers(workspaceId),
    enabled: Boolean(workspaceId) && canAssignOwners,
  });

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
  const { data: scheduleContact } = useContact(workspaceId, scheduleContactId ?? undefined);

  const sensors = useSensors(
    // Require a small drag distance so a plain click still opens the card.
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
  );

  const stages = useMemo<PipelineStage[]>(
    () => [...pipeline.stages].sort((a, b) => a.order - b.order),
    [pipeline.stages],
  );

  const listParams = useMemo(
    () => ({
      pipeline_id: pipeline.id,
      contact_id: customerFilter.id ? Number(customerFilter.id) : undefined,
      owner_id: repFilter === ALL_REPS_VALUE ? undefined : Number(repFilter),
    }),
    [pipeline.id, customerFilter.id, repFilter],
  );
  const listKey = queryKeys.opportunities.list(workspaceId, listParams);

  const { data, isPending, isError, refetch } = useQuery({
    queryKey: listKey,
    queryFn: () =>
      opportunitiesApi.list(workspaceId, {
        ...listParams,
        page_size: BOARD_PAGE_SIZE,
      }),
    enabled: !!workspaceId,
    staleTime: BOARD_STALE_TIME_MS,
    placeholderData: keepPreviousData,
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
              : opp,
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

  const removeMutation = useMutation({
    mutationFn: (opportunityId: string) =>
      opportunitiesApi.removeFromPipeline(workspaceId, opportunityId),
    onSuccess: () => {
      toast.success("Removed from the pipeline");
      setPendingRemoval(null);
    },
    onError: (err) => toast.error(getApiErrorMessage(err, "Failed to remove from the pipeline")),
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

  const activeOpportunity = activeId ? opportunities.find((o) => o.id === activeId) : undefined;

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
    return <PageErrorState message="Couldn't load opportunities." onRetry={() => void refetch()} />;
  }

  return (
    <>
      <div className="flex h-full min-h-0 min-w-0 flex-col gap-4">
        <div className="flex shrink-0 flex-col items-stretch gap-3 sm:flex-row sm:items-center sm:justify-between">
          <span className="text-sm font-medium text-muted-foreground">{pipeline.name}</span>
          <div className="flex flex-wrap items-center gap-2 sm:justify-end">
            <Button
              size="sm"
              variant="outline"
              onClick={() => setManageStagesOpen(true)}
              className="flex-1 sm:flex-none"
              data-testid="manage-stages"
            >
              <Settings2 className="mr-1.5 h-4 w-4" />
              Manage stages
            </Button>
            <Button
              size="sm"
              className="flex-1 sm:flex-none"
              onClick={() => openCreate()}
              data-testid="add-opportunity"
            >
              <Plus className="mr-1.5 h-4 w-4" />
              Add Opportunity
            </Button>
          </div>
        </div>

        <div className="flex w-full shrink-0 flex-col gap-3 sm:flex-row">
          <div className="w-full max-w-sm space-y-1.5">
            <Label htmlFor="opportunity-customer-filter" className="text-xs">
              Filter by customer
            </Label>
            <ContactPicker
              id="opportunity-customer-filter"
              workspaceId={workspaceId}
              value={customerFilter.id}
              initialContact={customerFilter.contact}
              onChange={(id, contact) => setCustomerFilter({ id, contact })}
              placeholder="Filter by customer…"
              data-testid="opportunity-customer-filter"
            />
          </div>

          {canAssignOwners ? (
            <div className="w-full max-w-xs space-y-1.5">
              <Label htmlFor="opportunity-rep-filter" className="text-xs">
                Filter by rep
              </Label>
              <Select
                value={repFilter}
                onValueChange={setRepFilter}
                disabled={repsQuery.isLoading || repsQuery.isError}
              >
                <SelectTrigger
                  id="opportunity-rep-filter"
                  className="w-full"
                  data-testid="opportunity-rep-filter"
                >
                  <SelectValue placeholder={repsQuery.isLoading ? "Loading team…" : "All reps"} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL_REPS_VALUE}>All reps</SelectItem>
                  {repsQuery.data?.map((member) => (
                    <SelectItem key={member.id} value={String(member.id)}>
                      {member.full_name || member.email}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          ) : null}
        </div>

        <DndContext sensors={sensors} onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
          <HorizontalScroll
            aria-label="Opportunity stages, scroll horizontally"
            className="min-h-0 flex-1"
            viewportClassName="h-full overflow-y-hidden"
            data-testid="opportunity-board-scroll"
          >
            <div className="flex h-full min-w-max gap-4 pr-1">
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
                  onRemove={setPendingRemoval}
                />
              ))}
            </div>
          </HorizontalScroll>

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
        canAssignOwners={canAssignOwners}
        open={detailOpen}
        onOpenChange={setDetailOpen}
      />

      <OpportunityCreateSheet
        workspaceId={workspaceId}
        pipelineId={pipeline.id}
        stages={stages}
        defaultStageId={createStageId}
        canAssignOwners={canAssignOwners}
        open={createOpen}
        onOpenChange={setCreateOpen}
      />

      <ManageStagesDialog
        workspaceId={workspaceId}
        pipeline={pipeline}
        open={manageStagesOpen}
        onOpenChange={setManageStagesOpen}
      />

      <AlertDialog
        open={!!pendingRemoval}
        onOpenChange={(open) => {
          if (!open) setPendingRemoval(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Remove {pendingRemoval?.name} from the pipeline?</AlertDialogTitle>
            <AlertDialogDescription>
              The deal and its history are kept, but the card leaves the board and automation will
              not put it back — including the next time you send this customer a quote. You can
              always add a deal for them manually.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={removeMutation.isPending}>Keep it</AlertDialogCancel>
            <AlertDialogAction
              disabled={removeMutation.isPending}
              onClick={(event) => {
                // Removal is a request, not a navigation: keep the dialog up
                // until the server confirms so a failure can be shown.
                event.preventDefault();
                if (pendingRemoval) removeMutation.mutate(pendingRemoval.id);
              }}
            >
              {removeMutation.isPending ? "Removing…" : "Remove from pipeline"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

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
  onRemove,
}: {
  stage: PipelineStage;
  stages: PipelineStage[];
  opportunities: Opportunity[];
  onOpen: (opportunityId: string) => void;
  onAdd: () => void;
  onMove: (opportunityId: string, stageId: string) => void;
  onCall: (opportunity: Opportunity) => void;
  onSchedule: (opportunity: Opportunity) => void;
  onRemove: (opportunity: Opportunity) => void;
}) {
  const { setNodeRef, isOver } = useDroppable({ id: stage.id });

  return (
    <div
      ref={setNodeRef}
      data-testid={`stage-column-${stage.id}`}
      className={cn(
        "flex h-full min-h-0 w-72 shrink-0 flex-col rounded-lg border bg-muted/30",
        isOver && "ring-2 ring-primary",
      )}
    >
      <div className="flex shrink-0 items-center justify-between gap-2 border-b px-3 py-2.5">
        <div className="flex items-center gap-2">
          <span
            className={cn(
              "h-2.5 w-2.5 rounded-full",
              STAGE_ACCENT[stage.stage_type] ?? "bg-muted-foreground",
            )}
          />
          <span className="text-sm font-medium">{stage.name}</span>
        </div>
        <Badge variant="secondary" className="text-xs">
          {opportunities.length}
        </Badge>
      </div>

      <div
        data-slot="opportunity-stage-scroll"
        className="app-scrollbar flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto p-2 [scrollbar-gutter:stable]"
      >
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
              onRemove={onRemove}
            />
          ))
        )}
      </div>
    </div>
  );
}
