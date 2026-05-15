"use client";

import { useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import * as z from "zod";
import { Loader2 } from "lucide-react";

import { workspacesApi, type CreateWorkspaceRequest } from "@/lib/api/workspaces";
import { queryKeys } from "@/lib/query-keys";
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
  FormDescription,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

const workspaceFormSchema = z.object({
  name: z.string().min(1, { error: "Name is required" }).max(200, { error: "Name must be 200 characters or less" }),
  slug: z
    .string()
    .min(1, { error: "Slug is required" })
    .max(100, { error: "Slug must be 100 characters or less" })
    .regex(/^[a-z0-9-]+$/, "Slug must contain only lowercase letters, numbers, and hyphens"),
  description: z.string().optional(),
});

type WorkspaceFormValues = z.infer<typeof workspaceFormSchema>;

function generateSlug(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, "")
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-")
    .slice(0, 100);
}

interface CreateWorkspaceDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function CreateWorkspaceDialog({ open, onOpenChange }: CreateWorkspaceDialogProps) {
  const queryClient = useQueryClient();
  const [isSubmitting, setIsSubmitting] = useState(false);

  const form = useForm<WorkspaceFormValues>({
    resolver: zodResolver(workspaceFormSchema),
    defaultValues: {
      name: "",
      slug: "",
      description: "",
    },
  });

  const createWorkspaceMutation = useMutation({
    mutationFn: (data: CreateWorkspaceRequest) => workspacesApi.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.workspaces.all() });
      toast.success("Workspace created successfully!");
      form.reset();
      onOpenChange(false);
    },
    onError: (error: Error) => {
      if (error.message.includes("slug already exists")) {
        form.setError("slug", { message: "This slug is already taken" });
      } else {
        toast.error("Failed to create workspace. Please try again.");
      }
    },
    onSettled: () => {
      setIsSubmitting(false);
    },
  });

  const handleSubmit = (data: WorkspaceFormValues) => {
    if (isSubmitting) return;
    setIsSubmitting(true);

    const request: CreateWorkspaceRequest = {
      name: data.name,
      slug: data.slug,
      description: data.description || undefined,
    };

    createWorkspaceMutation.mutate(request);
  };

  const handleNameChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const name = e.target.value;
    form.setValue("name", name);
    // Auto-generate slug from name if slug is empty or was auto-generated
    const currentSlug = form.getValues("slug");
    const previousName = form.getValues("name");
    if (!currentSlug || currentSlug === generateSlug(previousName)) {
      form.setValue("slug", generateSlug(name));
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[450px]">
        <DialogHeader>
          <DialogTitle>Create Workspace</DialogTitle>
          <DialogDescription>
            Create a new workspace to organize your contacts, campaigns, and team.
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(handleSubmit)} className="space-y-4">
            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Name *</FormLabel>
                  <FormControl>
                    <Input
                      placeholder="My Company"
                      {...field}
                      onChange={handleNameChange}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="slug"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Slug *</FormLabel>
                  <FormControl>
                    <Input placeholder="my-company" {...field} />
                  </FormControl>
                  <FormDescription>
                    URL-friendly identifier (lowercase, numbers, hyphens only)
                  </FormDescription>
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
                      placeholder="A brief description of this workspace..."
                      className="min-h-[80px]"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

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
                {isSubmitting ? "Creating..." : "Create Workspace"}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
