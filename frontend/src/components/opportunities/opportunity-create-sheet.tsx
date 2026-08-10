"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import * as z from "zod";

import { Button } from "@/components/ui/button";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
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
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import { TeamMemberPicker } from "@/components/workspaces/team-member-picker";
import { opportunitiesApi } from "@/lib/api/opportunities";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";
import type { Opportunity, PipelineStage } from "@/types";

const createOpportunitySchema = z.object({
  name: z.string().trim().min(1, { error: "Name is required" }),
  stage_id: z.string().min(1, { error: "Please select a stage" }),
  assigned_user_id: z.number().nullable(),
  amount: z
    .string()
    .trim()
    .refine((v) => v === "" || (!Number.isNaN(Number(v)) && Number(v) >= 0), {
      error: "Enter a valid amount",
    }),
  description: z.string(),
});

type CreateOpportunityFormValues = z.infer<typeof createOpportunitySchema>;

interface OpportunityCreateSheetProps {
  workspaceId: string;
  pipelineId: string;
  stages: PipelineStage[];
  /** Stage to pre-select (e.g. the column the user added from). */
  defaultStageId?: string;
  canAssignOwners: boolean;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function OpportunityCreateSheet({
  workspaceId,
  pipelineId,
  stages,
  defaultStageId,
  canAssignOwners,
  open,
  onOpenChange,
}: OpportunityCreateSheetProps) {
  const queryClient = useQueryClient();
  const initialStageId = defaultStageId ?? stages[0]?.id ?? "";

  const form = useForm<CreateOpportunityFormValues>({
    resolver: zodResolver(createOpportunitySchema),
    defaultValues: {
      name: "",
      stage_id: initialStageId,
      assigned_user_id: null,
      amount: "",
      description: "",
    },
  });

  // Re-sync the pre-selected stage whenever the sheet (re)opens from a column.
  useEffect(() => {
    if (open) {
      form.reset({
        name: "",
        stage_id: initialStageId,
        assigned_user_id: null,
        amount: "",
        description: "",
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, initialStageId]);

  const createMutation = useMutation({
    mutationFn: (values: CreateOpportunityFormValues): Promise<Opportunity> => {
      const amount = values.amount.trim();
      return opportunitiesApi.create(workspaceId, {
        name: values.name.trim(),
        pipeline_id: pipelineId,
        stage_id: values.stage_id,
        description: values.description.trim() || undefined,
        amount: amount === "" ? undefined : Number(amount),
        assigned_user_id: canAssignOwners ? values.assigned_user_id : undefined,
      });
    },
    onSuccess: () => {
      toast.success("Opportunity created");
      void queryClient.invalidateQueries({
        queryKey: queryKeys.opportunities.all(workspaceId),
      });
      onOpenChange(false);
    },
    onError: (err: unknown) =>
      toast.error(getApiErrorMessage(err, "Failed to create opportunity")),
  });

  const handleOpenChange = (next: boolean) => {
    if (!next && createMutation.isPending) return;
    onOpenChange(next);
  };

  return (
    <Sheet open={open} onOpenChange={handleOpenChange}>
      <SheetContent className="flex w-full flex-col gap-0 overflow-y-auto sm:max-w-md">
        <SheetHeader>
          <SheetTitle>Add Opportunity</SheetTitle>
          <SheetDescription>
            Create a new deal and place it in a pipeline stage.
          </SheetDescription>
        </SheetHeader>

        <Form {...form}>
          <form
            onSubmit={form.handleSubmit((values) => createMutation.mutate(values))}
            className="space-y-4 px-4 pb-6"
          >
            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Name *</FormLabel>
                  <FormControl>
                    <Input
                      placeholder="e.g. Acme Corp — annual plan"
                      data-testid="opportunity-name-input"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="stage_id"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Stage *</FormLabel>
                  <Select onValueChange={field.onChange} value={field.value}>
                    <FormControl>
                      <SelectTrigger
                        className="w-full"
                        data-testid="opportunity-stage-select"
                      >
                        <SelectValue placeholder="Select a stage" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {stages.map((stage) => (
                        <SelectItem key={stage.id} value={stage.id}>
                          {stage.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FormMessage />
                </FormItem>
              )}
            />

            {canAssignOwners ? (
              <FormField
                control={form.control}
                name="assigned_user_id"
                render={({ field }) => (
                  <TeamMemberPicker
                    workspaceId={workspaceId}
                    value={field.value}
                    onValueChange={field.onChange}
                    label="Owner"
                    triggerId="opportunity-owner"
                    disabled={createMutation.isPending}
                  />
                )}
              />
            ) : null}

            <FormField
              control={form.control}
              name="amount"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Amount</FormLabel>
                  <FormControl>
                    <Input
                      type="number"
                      min="0"
                      step="0.01"
                      inputMode="decimal"
                      placeholder="0.00"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="description"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Description</FormLabel>
                  <FormControl>
                    <Textarea
                      placeholder="Add context about this deal..."
                      className="min-h-[80px]"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <SheetFooter className="px-0">
              <Button
                type="button"
                variant="outline"
                onClick={() => handleOpenChange(false)}
                disabled={createMutation.isPending}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={createMutation.isPending}>
                {createMutation.isPending && (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                )}
                {createMutation.isPending ? "Creating..." : "Create Opportunity"}
              </Button>
            </SheetFooter>
          </form>
        </Form>
      </SheetContent>
    </Sheet>
  );
}
