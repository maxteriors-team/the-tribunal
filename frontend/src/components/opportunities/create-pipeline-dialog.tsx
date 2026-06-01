"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import * as z from "zod";

import {
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { FormDialog } from "@/components/ui/form-dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { opportunitiesApi, type CreatePipelineRequest } from "@/lib/api/opportunities";
import { useFormDialog } from "@/lib/forms/use-form-dialog";
import { queryKeys } from "@/lib/query-keys";

const pipelineFormSchema = z.object({
  name: z.string().min(1, { error: "Pipeline name is required" }).max(255, { error: "Name must be 255 characters or less" }),
  description: z.string().max(500, { error: "Description must be 500 characters or less" }).optional().or(z.literal("")),
});

type PipelineFormValues = z.infer<typeof pipelineFormSchema>;

const defaultValues: PipelineFormValues = {
  name: "",
  description: "",
};

interface CreatePipelineDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  workspaceId: string;
}

export function CreatePipelineDialog({ open, onOpenChange, workspaceId }: CreatePipelineDialogProps) {
  const queryClient = useQueryClient();

  const createPipelineMutation = useMutation({
    mutationFn: (data: CreatePipelineRequest) => opportunitiesApi.createPipeline(workspaceId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.opportunities.pipelines(workspaceId ?? "") });
      toast.success("Pipeline created successfully!");
    },
  });

  const dialog = useFormDialog<PipelineFormValues>({
    open,
    onOpenChange,
    schema: pipelineFormSchema,
    defaultValues,
    errorFallback: "Failed to create pipeline. Please try again.",
    onTopLevelError: (message) => toast.error(message),
    onSubmit: async (data) => {
      await createPipelineMutation.mutateAsync({
        name: data.name,
        description: data.description || undefined,
      });
      onOpenChange(false);
    },
  });

  const { form } = dialog;

  return (
    <FormDialog
      dialog={dialog}
      open={open}
      title="Create Pipeline"
      description="Create a new sales pipeline to track your deals and leads."
      submitLabel="Create Pipeline"
      submitBusyLabel="Creating..."
      className="sm:max-w-[500px]"
    >
      <FormField
        control={form.control}
        name="name"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Pipeline Name *</FormLabel>
            <FormControl>
              <Input placeholder="e.g., Enterprise Sales, SMB Pipeline" {...field} />
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
                placeholder="Add details about this pipeline..."
                className="min-h-[80px]"
                {...field}
              />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />

      <div className="rounded-md bg-muted p-3 text-sm text-muted-foreground">
        <p className="font-medium mb-2">Default stages will be created:</p>
        <ul className="list-disc list-inside space-y-1 text-xs">
          <li>New (0% probability)</li>
          <li>Qualified (25% probability)</li>
          <li>Proposal (50% probability)</li>
          <li>Won (100% probability)</li>
          <li>Lost (0% probability)</li>
        </ul>
      </div>
    </FormDialog>
  );
}
