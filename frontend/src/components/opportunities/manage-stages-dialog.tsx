"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Loader2, Plus } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  opportunitiesApi,
  type CreatePipelineStageRequest,
  type UpdatePipelineStageRequest,
} from "@/lib/api/opportunities";
import { queryKeys } from "@/lib/query-keys";
import { cn } from "@/lib/utils";
import { getApiErrorMessage } from "@/lib/utils/errors";
import type { Pipeline, PipelineStage, PipelineStageType } from "@/types";

const STAGE_ACCENT: Record<string, string> = {
  active: "bg-blue-500",
  won: "bg-green-500",
  lost: "bg-red-500",
};

const STAGE_TYPE_OPTIONS: { value: PipelineStageType; label: string }[] = [
  { value: "active", label: "Active" },
  { value: "won", label: "Won" },
  { value: "lost", label: "Lost" },
];

interface ManageStagesDialogProps {
  workspaceId: string;
  pipeline: Pipeline;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function ManageStagesDialog({
  workspaceId,
  pipeline,
  open,
  onOpenChange,
}: ManageStagesDialogProps) {
  const queryClient = useQueryClient();

  const stages = useMemo<PipelineStage[]>(
    () => [...pipeline.stages].sort((a, b) => a.order - b.order),
    [pipeline.stages]
  );

  // Draft stage names keyed by stage id; a row falls back to the server value
  // when no draft exists. Drafts are cleared after a successful save and when
  // the dialog closes so rows always reflect fresh data.
  const [nameDrafts, setNameDrafts] = useState<Record<string, string>>({});
  const [newStageName, setNewStageName] = useState("");

  const invalidatePipelines = () =>
    queryClient.invalidateQueries({
      queryKey: queryKeys.opportunities.pipelines(workspaceId),
    });

  const createMutation = useMutation({
    mutationFn: (data: CreatePipelineStageRequest) =>
      opportunitiesApi.createStage(workspaceId, pipeline.id, data),
    onSuccess: (stage) => {
      toast.success(`Added “${stage.name}”`);
      setNewStageName("");
    },
    onError: (err) => toast.error(getApiErrorMessage(err, "Failed to add stage")),
    onSettled: () => void invalidatePipelines(),
  });

  const updateMutation = useMutation({
    mutationFn: ({
      stageId,
      data,
    }: {
      stageId: string;
      data: UpdatePipelineStageRequest;
    }) => opportunitiesApi.updateStage(workspaceId, pipeline.id, stageId, data),
    onSuccess: (stage, variables) => {
      toast.success(`Updated “${stage.name}”`);
      // Only a rename should drop the draft (so the row reflects the fresh
      // server value). A type change must not wipe an unsaved name edit.
      if (variables.data.name === undefined) return;
      setNameDrafts((prev) => {
        if (!(stage.id in prev)) return prev;
        const next = { ...prev };
        delete next[stage.id];
        return next;
      });
    },
    onError: (err) =>
      toast.error(getApiErrorMessage(err, "Failed to update stage")),
    onSettled: () => void invalidatePipelines(),
  });

  const reorderMutation = useMutation({
    // There is no unique constraint on `order`, so swapping the two neighbours'
    // order values is safe. Run both PUTs, then invalidate once settled.
    mutationFn: async ({ a, b }: { a: PipelineStage; b: PipelineStage }) => {
      await Promise.all([
        opportunitiesApi.updateStage(workspaceId, pipeline.id, a.id, {
          order: b.order,
        }),
        opportunitiesApi.updateStage(workspaceId, pipeline.id, b.id, {
          order: a.order,
        }),
      ]);
    },
    onError: (err) =>
      toast.error(getApiErrorMessage(err, "Failed to reorder stages")),
    onSettled: () => void invalidatePipelines(),
  });

  const busy =
    createMutation.isPending ||
    updateMutation.isPending ||
    reorderMutation.isPending;

  const handleRename = (stage: PipelineStage) => {
    const name = (nameDrafts[stage.id] ?? stage.name).trim();
    if (!name || name === stage.name) return;
    updateMutation.mutate({ stageId: stage.id, data: { name } });
  };

  const handleTypeChange = (
    stage: PipelineStage,
    stageType: PipelineStageType
  ) => {
    if (stageType === stage.stage_type) return;
    updateMutation.mutate({
      stageId: stage.id,
      data: { stage_type: stageType },
    });
  };

  const handleReorder = (index: number, direction: -1 | 1) => {
    const a = stages[index];
    const b = stages[index + direction];
    if (!a || !b) return;
    reorderMutation.mutate({ a, b });
  };

  const handleAdd = () => {
    const name = newStageName.trim();
    if (!name) return;
    const maxOrder = stages.reduce((max, s) => Math.max(max, s.order), -1);
    createMutation.mutate({
      name,
      order: maxOrder + 1,
      probability: 0,
      stage_type: "active",
    });
  };

  const handleOpenChange = (next: boolean) => {
    if (!next && busy) return;
    if (!next) {
      setNameDrafts({});
      setNewStageName("");
    }
    onOpenChange(next);
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Manage stages</DialogTitle>
          <DialogDescription>
            Rename, reorder, and add stages for “{pipeline.name}”. Existing
            opportunities keep their place when you rename or reorder.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-2" data-testid="manage-stages-list">
          {stages.map((stage, index) => {
            const draftName = nameDrafts[stage.id] ?? stage.name;
            const trimmed = draftName.trim();
            const dirty = trimmed !== "" && trimmed !== stage.name;
            return (
              <div
                key={stage.id}
                className="flex items-center gap-2 rounded-md border bg-muted/20 p-2"
                data-testid={`manage-stage-row-${stage.id}`}
              >
                <span
                  aria-hidden
                  className={cn(
                    "h-2.5 w-2.5 shrink-0 rounded-full",
                    STAGE_ACCENT[stage.stage_type] ?? "bg-muted-foreground"
                  )}
                />
                <Input
                  value={draftName}
                  onChange={(e) =>
                    setNameDrafts((prev) => ({
                      ...prev,
                      [stage.id]: e.target.value,
                    }))
                  }
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      handleRename(stage);
                    }
                  }}
                  className="h-8 flex-1"
                  aria-label={`Stage name for ${stage.name}`}
                />
                <Select
                  value={stage.stage_type}
                  onValueChange={(v) =>
                    handleTypeChange(stage, v as PipelineStageType)
                  }
                  disabled={busy}
                >
                  <SelectTrigger
                    size="sm"
                    className="w-[7.5rem] shrink-0"
                    aria-label={`Stage type for ${stage.name}`}
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {STAGE_TYPE_OPTIONS.map((opt) => (
                      <SelectItem key={opt.value} value={opt.value}>
                        {opt.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <div className="flex shrink-0">
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`Move ${stage.name} up`}
                    disabled={busy || index === 0}
                    onClick={() => handleReorder(index, -1)}
                  >
                    <ArrowUp className="h-4 w-4" />
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`Move ${stage.name} down`}
                    disabled={busy || index === stages.length - 1}
                    onClick={() => handleReorder(index, 1)}
                  >
                    <ArrowDown className="h-4 w-4" />
                  </Button>
                </div>
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  className="shrink-0"
                  disabled={busy || !dirty}
                  onClick={() => handleRename(stage)}
                >
                  Save
                </Button>
              </div>
            );
          })}
        </div>

        <div className="mt-2 flex items-end gap-2 border-t pt-4">
          <div className="flex-1 space-y-1.5">
            <Label htmlFor="new-stage-name">Add a stage</Label>
            <Input
              id="new-stage-name"
              placeholder="e.g. Estimate Scheduled"
              value={newStageName}
              onChange={(e) => setNewStageName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  handleAdd();
                }
              }}
              disabled={createMutation.isPending}
            />
          </div>
          <Button
            type="button"
            onClick={handleAdd}
            disabled={createMutation.isPending || newStageName.trim() === ""}
            data-testid="add-stage"
          >
            {createMutation.isPending ? (
              <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
            ) : (
              <Plus className="mr-1.5 h-4 w-4" />
            )}
            Add stage
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
