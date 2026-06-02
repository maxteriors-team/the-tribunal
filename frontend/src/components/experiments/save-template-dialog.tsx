"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Save } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { messageTemplatesApi } from "@/lib/api/message-templates";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";

interface SaveTemplateDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  messageTemplate: string;
  defaultName?: string;
}

export function SaveTemplateDialog({
  open,
  onOpenChange,
  messageTemplate,
  defaultName = "",
}: SaveTemplateDialogProps) {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();
  const [name, setName] = useState(defaultName);

  const saveMutation = useMutation({
    mutationFn: () => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      return messageTemplatesApi.create(workspaceId, {
        name,
        message_template: messageTemplate,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.messageTemplates.all(workspaceId ?? ""),
      });
      toast.success("Template saved successfully");
      setName("");
      onOpenChange(false);
    },
    onError: (err: unknown) => {
      toast.error(getApiErrorMessage(err, "Failed to save template"));
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) {
      toast.error("Please enter a template name");
      return;
    }
    saveMutation.mutate();
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[450px]">
        <DialogHeader>
          <DialogTitle>Save as Template</DialogTitle>
          <DialogDescription>
            Save this message variation for reuse in future experiments.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="template-name">Template Name</Label>
            <Input
              id="template-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g., Friendly Introduction"
              // The dialog opens specifically so the user can type a name;
              // focusing the field on open matches the dialog focus-trap pattern.
              // eslint-disable-next-line jsx-a11y/no-autofocus
              autoFocus
            />
          </div>

          <div className="space-y-2">
            <Label>Message Preview</Label>
            <div className="p-3 bg-muted rounded-md text-sm whitespace-pre-wrap max-h-32 overflow-y-auto">
              {messageTemplate || "No message content"}
            </div>
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={saveMutation.isPending || !name.trim()}>
              {saveMutation.isPending ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Save className="mr-2 h-4 w-4" />
              )}
              {saveMutation.isPending ? "Saving..." : "Save Template"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
