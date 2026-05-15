"use client";

import { useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import * as z from "zod";
import { Loader2 } from "lucide-react";

import { opportunitiesApi, type CreatePipelineRequest } from "@/lib/api/opportunities";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

const pipelineFormSchema = z.object({
  name: z.string().min(1, { error: "Pipeline name is required" }).max(255, { error: "Name must be 255 characters or less" }),
  description: z.string().max(500, { error: "Description must be 500 characters or less" }).optional().or(z.literal("")),
});

type PipelineFormValues = z.infer<typeof pipelineFormSchema>;

interface CreatePipelineDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  workspaceId: string;
}

export function CreatePipelineDialog({ open, onOpenChange, workspaceId }: CreatePipelineDialogProps) {
  const queryClient = useQueryClient();
  const [isSubmitting, setIsSubmitting] = useState(false);

  const form = useForm<PipelineFormValues>({
    resolver: zodResolver(pipelineFormSchema),
    defaultValues: {
      name: "",
      description: "",
    },
  });

  const createPipelineMutation = useMutation({
    mutationFn: (data: CreatePipelineRequest) => {
      return opportunitiesApi.createPipeline(workspaceId, data);
    },
    onSuccess: () => {
      // Invalidate pipelines query to trigger a refetch
      queryClient.invalidateQueries({ queryKey: queryKeys.opportunities.pipelines(workspaceId ?? "") });
      toast.success("Pipeline created successfully!");
      form.reset();
      onOpenChange(false);
    },
    onError: (error) => {
      toast.error(getApiErrorMessage(error, "Failed to create pipeline. Please try again."));
    },
    onSettled: () => {
      setIsSubmitting(false);
    },
  });

  const handleSubmit = (data: PipelineFormValues) => {
    if (isSubmitting) return;
    setIsSubmitting(true);

    const request: CreatePipelineRequest = {
      name: data.name,
      description: data.description || undefined,
    };

    createPipelineMutation.mutate(request);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle>Create Pipeline</DialogTitle>
          <DialogDescription>
            Create a new sales pipeline to track your deals and leads.
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(handleSubmit)} className="space-y-4">
            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Pipeline Name *</FormLabel>
                  <FormControl>
                    <Input
                      placeholder="e.g., Enterprise Sales, SMB Pipeline"
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

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => onOpenChange(false)}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={isSubmitting}>
                {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {isSubmitting ? "Creating..." : "Create Pipeline"}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
