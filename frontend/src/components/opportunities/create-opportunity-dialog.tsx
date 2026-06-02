"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useWatch } from "react-hook-form";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { opportunitiesApi } from "@/lib/api/opportunities";
import { useFormDialog } from "@/lib/forms/use-form-dialog";
import { queryKeys } from "@/lib/query-keys";

const opportunityFormSchema = z.object({
  name: z
    .string()
    .min(1, { error: "Opportunity name is required" })
    .max(255, { error: "Name must be 255 characters or less" }),
  description: z
    .string()
    .max(2000, { error: "Description must be 2000 characters or less" })
    .optional()
    .or(z.literal("")),
  amount: z
    .string()
    .refine(
      (val) => val === "" || (!isNaN(parseFloat(val)) && parseFloat(val) >= 0),
      { error: "Amount must be a non-negative number" },
    ),
  currency: z.string().min(1),
  pipeline_id: z.string().min(1, { error: "Pipeline is required" }),
  stage_id: z.string().optional().or(z.literal("")),
});

type OpportunityFormValues = z.infer<typeof opportunityFormSchema>;

const defaultValues: OpportunityFormValues = {
  name: "",
  description: "",
  amount: "",
  currency: "USD",
  pipeline_id: "",
  stage_id: "",
};

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

  const createMutation = useMutation({
    mutationFn: (data: OpportunityFormValues) =>
      opportunitiesApi.create(workspaceId, {
        name: data.name,
        description: data.description || undefined,
        amount: data.amount ? parseFloat(data.amount) : undefined,
        currency: data.currency,
        pipeline_id: data.pipeline_id,
        stage_id: data.stage_id || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.opportunities.all(workspaceId ?? "") });
      toast.success("Opportunity created");
    },
  });

  const dialog = useFormDialog<OpportunityFormValues>({
    open,
    onOpenChange,
    schema: opportunityFormSchema,
    defaultValues,
    errorFallback: "Failed to create opportunity",
    onTopLevelError: (message) => toast.error(message),
    onSubmit: async (data) => {
      await createMutation.mutateAsync(data);
      onOpenChange(false);
    },
  });

  const { form } = dialog;

  const pipelineId = useWatch({ control: form.control, name: "pipeline_id" });

  const { data: pipelines } = useQuery({
    queryKey: queryKeys.opportunities.pipelines(workspaceId ?? ""),
    queryFn: () => opportunitiesApi.listPipelines(workspaceId),
    enabled: !!workspaceId && open,
  });

  const selectedPipeline = pipelines?.find((p) => p.id === pipelineId);

  return (
    <FormDialog
      dialog={dialog}
      open={open}
      title="Create Opportunity"
      description="Add a new opportunity to your pipeline"
      submitLabel="Create"
      submitBusyLabel="Creating..."
      className="sm:max-w-[500px]"
    >
      <FormField
        control={form.control}
        name="name"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Opportunity Name *</FormLabel>
            <FormControl>
              <Input placeholder="e.g., ABC Corp Contract" {...field} />
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
                placeholder="Add details about this opportunity..."
                rows={3}
                {...field}
              />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />

      <div className="grid grid-cols-2 gap-4">
        <FormField
          control={form.control}
          name="amount"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Amount</FormLabel>
              <FormControl>
                <Input type="number" placeholder="0.00" step="0.01" {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />

        <FormField
          control={form.control}
          name="currency"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Currency</FormLabel>
              <Select value={field.value} onValueChange={field.onChange}>
                <FormControl>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                </FormControl>
                <SelectContent>
                  <SelectItem value="USD">USD</SelectItem>
                  <SelectItem value="EUR">EUR</SelectItem>
                  <SelectItem value="GBP">GBP</SelectItem>
                  <SelectItem value="CAD">CAD</SelectItem>
                </SelectContent>
              </Select>
              <FormMessage />
            </FormItem>
          )}
        />
      </div>

      <FormField
        control={form.control}
        name="pipeline_id"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Pipeline *</FormLabel>
            <Select
              value={field.value}
              onValueChange={(value) => {
                field.onChange(value);
                form.setValue("stage_id", "");
              }}
            >
              <FormControl>
                <SelectTrigger>
                  <SelectValue placeholder="Select a pipeline" />
                </SelectTrigger>
              </FormControl>
              <SelectContent>
                {pipelines?.map((p) => (
                  <SelectItem key={p.id} value={p.id}>
                    {p.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <FormMessage />
          </FormItem>
        )}
      />

      {selectedPipeline && (
        <FormField
          control={form.control}
          name="stage_id"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Stage</FormLabel>
              <Select value={field.value} onValueChange={field.onChange}>
                <FormControl>
                  <SelectTrigger>
                    <SelectValue placeholder="Select a stage" />
                  </SelectTrigger>
                </FormControl>
                <SelectContent>
                  {selectedPipeline.stages.map((s) => (
                    <SelectItem key={s.id} value={s.id}>
                      {s.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <FormMessage />
            </FormItem>
          )}
        />
      )}
    </FormDialog>
  );
}
