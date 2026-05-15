"use client";

import * as React from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { opportunitiesApi } from "@/lib/api/opportunities";
import { queryKeys } from "@/lib/query-keys";
import { useQueryClient } from "@tanstack/react-query";

interface CreateOpportunityDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  workspaceId: string;
}

export function CreateOpportunityDialog({
  open,
  onOpenChange,
  workspaceId,
}: CreateOpportunityDialogProps) {
  const queryClient = useQueryClient();
  const [formData, setFormData] = React.useState({
    name: "",
    description: "",
    amount: "",
    currency: "USD",
    pipeline_id: "",
    stage_id: "",
  });

  const { data: pipelines } = useQuery({
    queryKey: queryKeys.opportunities.pipelines(workspaceId ?? ""),
    queryFn: () => opportunitiesApi.listPipelines(workspaceId),
    enabled: !!workspaceId && open,
  });

  const selectedPipeline = pipelines?.find((p) => p.id === formData.pipeline_id);

  const createMutation = useMutation({
    mutationFn: () =>
      opportunitiesApi.create(workspaceId, {
        name: formData.name,
        description: formData.description || undefined,
        amount: formData.amount ? parseFloat(formData.amount) : undefined,
        currency: formData.currency,
        pipeline_id: formData.pipeline_id,
        stage_id: formData.stage_id || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.opportunities.bare(workspaceId ?? "") });
      setFormData({
        name: "",
        description: "",
        amount: "",
        currency: "USD",
        pipeline_id: "",
        stage_id: "",
      });
      onOpenChange(false);
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!formData.name || !formData.pipeline_id) return;
    createMutation.mutate();
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle>Create Opportunity</DialogTitle>
          <DialogDescription>
            Add a new opportunity to your pipeline
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="name">Opportunity Name *</Label>
            <Input
              id="name"
              placeholder="e.g., ABC Corp Contract"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              required
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="description">Description</Label>
            <Textarea
              id="description"
              placeholder="Add details about this opportunity..."
              value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              rows={3}
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="amount">Amount</Label>
              <Input
                id="amount"
                type="number"
                placeholder="0.00"
                value={formData.amount}
                onChange={(e) => setFormData({ ...formData, amount: e.target.value })}
                step="0.01"
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="currency">Currency</Label>
              <Select value={formData.currency} onValueChange={(value) => setFormData({ ...formData, currency: value })}>
                <SelectTrigger id="currency">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="USD">USD</SelectItem>
                  <SelectItem value="EUR">EUR</SelectItem>
                  <SelectItem value="GBP">GBP</SelectItem>
                  <SelectItem value="CAD">CAD</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="pipeline">Pipeline *</Label>
            <Select value={formData.pipeline_id} onValueChange={(value) => setFormData({ ...formData, pipeline_id: value, stage_id: "" })}>
              <SelectTrigger id="pipeline">
                <SelectValue placeholder="Select a pipeline" />
              </SelectTrigger>
              <SelectContent>
                {pipelines?.map((p) => (
                  <SelectItem key={p.id} value={p.id}>
                    {p.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {selectedPipeline && (
            <div className="space-y-2">
              <Label htmlFor="stage">Stage</Label>
              <Select value={formData.stage_id} onValueChange={(value) => setFormData({ ...formData, stage_id: value })}>
                <SelectTrigger id="stage">
                  <SelectValue placeholder="Select a stage" />
                </SelectTrigger>
                <SelectContent>
                  {selectedPipeline.stages.map((s) => (
                    <SelectItem key={s.id} value={s.id}>
                      {s.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          <div className="flex justify-end gap-3 pt-4">
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={!formData.name || !formData.pipeline_id || createMutation.isPending}
            >
              {createMutation.isPending ? "Creating..." : "Create"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
