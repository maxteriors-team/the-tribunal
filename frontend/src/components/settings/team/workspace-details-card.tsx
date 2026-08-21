"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, Loader2, Save, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useSettingsSaveMutation } from "@/hooks/useSettingsSaveMutation";
import { workspacesApi } from "@/lib/api/workspaces";
import { queryKeys } from "@/lib/query-keys";
import {
  emptyWorkspaceFormValues,
  workspaceFormSchema,
  type WorkspaceFormValues,
} from "@/lib/schemas/team-settings";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { useWorkspace } from "@/providers/workspace-provider";

interface WorkspaceDetailsCardProps {
  workspaceId: string | null;
  canEditWorkspace: boolean;
  canDeleteWorkspace: boolean;
}

/**
 * Workspace identity card — name, description, default toggle, delete.
 * Uses react-hook-form for the editable fields so dirty/saved state is
 * derived from form state rather than ad-hoc useState.
 */
export function WorkspaceDetailsCard({
  workspaceId,
  canEditWorkspace,
  canDeleteWorkspace,
}: WorkspaceDetailsCardProps) {
  const { currentWorkspace, workspaces, setCurrentWorkspace } = useWorkspace();
  const queryClient = useQueryClient();
  const router = useRouter();
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [saved, setSaved] = useState(false);

  const form = useForm<WorkspaceFormValues>({
    resolver: zodResolver(workspaceFormSchema),
    defaultValues: emptyWorkspaceFormValues,
  });

  useEffect(() => {
    if (!currentWorkspace) return;
    form.reset({
      name: currentWorkspace.workspace.name ?? "",
      description: currentWorkspace.workspace.description ?? "",
    });
  }, [currentWorkspace, form]);

  const updateMutation = useSettingsSaveMutation({
    mutationFn: (data: { name?: string; description?: string }) =>
      workspacesApi.update(workspaceId!, data),
    successMessage: "Workspace details are up to date.",
    errorMessage: "We couldn't save workspace details. Check your connection and try again.",
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.workspaces.all() });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => workspacesApi.delete(workspaceId!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.workspaces.all() });
      toast.success("Workspace deleted successfully");
      setDeleteDialogOpen(false);
      const remaining = workspaces.filter((ws) => ws.workspace.id !== workspaceId);
      if (remaining.length > 0) {
        setCurrentWorkspace(remaining[0].workspace.id);
      } else {
        router.push("/");
      }
    },
    onError: (err: unknown) => {
      toast.error(getApiErrorMessage(err, "Failed to delete workspace"));
    },
  });

  const setDefaultMutation = useMutation({
    mutationFn: () => workspacesApi.setDefault(workspaceId!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.workspaces.all() });
      toast.success("Default workspace updated");
    },
    onError: (err: unknown) => {
      toast.error(getApiErrorMessage(err, "Failed to set default workspace"));
    },
  });

  const onSubmit = (data: WorkspaceFormValues) => {
    updateMutation.mutate({
      name: data.name || undefined,
      description: data.description || undefined,
    });
  };

  return (
    <form onSubmit={form.handleSubmit(onSubmit)}>
      <Card>
        <CardHeader>
          <CardTitle>Workspace Settings</CardTitle>
          <CardDescription>Manage your workspace details and configuration</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="workspaceName">Workspace Name</Label>
            <Input
              id="workspaceName"
              placeholder="My Workspace"
              disabled={!canEditWorkspace}
              {...form.register("name")}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="workspaceDescription">Description</Label>
            <Textarea
              id="workspaceDescription"
              placeholder="A brief description of this workspace..."
              className="min-h-[80px]"
              disabled={!canEditWorkspace}
              {...form.register("description")}
            />
          </div>
          <Separator />
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label htmlFor="default-workspace">Default Workspace</Label>
              <p className="text-sm text-muted-foreground">
                Set this as your default workspace when you log in
              </p>
            </div>
            <Switch
              id="default-workspace"
              checked={currentWorkspace?.is_default ?? false}
              onCheckedChange={() => setDefaultMutation.mutate()}
              disabled={setDefaultMutation.isPending || currentWorkspace?.is_default}
            />
          </div>
          {!canEditWorkspace && (
            <p className="text-sm text-muted-foreground">
              Only workspace owners and admins can edit these settings.
            </p>
          )}
        </CardContent>
        <CardFooter className="flex justify-between">
          <div>
            {canEditWorkspace && (
              <Button type="submit" disabled={updateMutation.isPending}>
                {updateMutation.isPending ? (
                  <>
                    <Loader2 className="mr-2 size-4 animate-spin" />
                    Saving...
                  </>
                ) : saved ? (
                  <>
                    <Check className="mr-2 size-4" />
                    Saved
                  </>
                ) : (
                  <>
                    <Save className="mr-2 size-4" />
                    Save Changes
                  </>
                )}
              </Button>
            )}
          </div>
          {canDeleteWorkspace && (
            <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
              <AlertDialogTrigger asChild>
                <Button type="button" variant="destructive">
                  <Trash2 className="mr-2 size-4" />
                  Delete Workspace
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Delete Workspace</AlertDialogTitle>
                  <AlertDialogDescription>
                    Are you sure you want to delete &quot;
                    {currentWorkspace?.workspace.name}&quot;? This action cannot be undone. All data
                    including contacts, campaigns, and team members will be permanently removed.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Cancel</AlertDialogCancel>
                  <AlertDialogAction
                    onClick={() => deleteMutation.mutate()}
                    className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                    disabled={deleteMutation.isPending}
                  >
                    {deleteMutation.isPending ? (
                      <>
                        <Loader2 className="mr-2 size-4 animate-spin" />
                        Deleting...
                      </>
                    ) : (
                      "Delete Workspace"
                    )}
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          )}
        </CardFooter>
      </Card>
    </form>
  );
}
