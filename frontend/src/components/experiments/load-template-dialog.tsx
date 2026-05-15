"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Loader2, Trash2, FileText, Check } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useWorkspaceId } from "@/hooks/use-workspace-id";
import { queryKeys } from "@/lib/query-keys";
import { messageTemplatesApi } from "@/lib/api/message-templates";
import type { MessageTemplate } from "@/types";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { formatDate } from "@/lib/utils/date";

interface LoadTemplateDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSelect: (template: MessageTemplate) => void;
}

export function LoadTemplateDialog({
  open,
  onOpenChange,
  onSelect,
}: LoadTemplateDialogProps) {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const { data, isPending } = useQuery({
    queryKey: queryKeys.messageTemplates.bare(workspaceId ?? ""),
    queryFn: () => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      return messageTemplatesApi.list(workspaceId);
    },
    enabled: !!workspaceId && open,
  });

  const deleteMutation = useMutation({
    mutationFn: (templateId: string) => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      return messageTemplatesApi.delete(workspaceId, templateId);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.messageTemplates.bare(workspaceId ?? ""),
      });
      toast.success("Template deleted");
    },
    onError: (err: unknown) => {
      toast.error(getApiErrorMessage(err, "Failed to delete template"));
    },
  });

  const templates = data?.items ?? [];

  const handleSelect = (template: MessageTemplate) => {
    onSelect(template);
    onOpenChange(false);
    toast.success(`Loaded template: ${template.name}`);
  };

  const handleDelete = (e: React.MouseEvent, templateId: string) => {
    e.stopPropagation();
    deleteMutation.mutate(templateId);
    if (selectedId === templateId) {
      setSelectedId(null);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle>Load Template</DialogTitle>
          <DialogDescription>
            Select a saved template to use for this variant.
          </DialogDescription>
        </DialogHeader>

        {isPending ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="size-8 animate-spin text-muted-foreground" />
          </div>
        ) : templates.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 text-center">
            <FileText className="size-12 text-muted-foreground mb-3" />
            <p className="text-muted-foreground">No saved templates yet</p>
            <p className="text-sm text-muted-foreground mt-1">
              Save a variant as a template to reuse it later
            </p>
          </div>
        ) : (
          <ScrollArea className="max-h-[400px] pr-4">
            <div className="space-y-2">
              {templates.map((template) => (
                <div
                  key={template.id}
                  className={`group relative p-3 rounded-lg border cursor-pointer transition-colors ${
                    selectedId === template.id
                      ? "border-primary bg-primary/5"
                      : "hover:border-muted-foreground/50 hover:bg-muted/50"
                  }`}
                  onClick={() => setSelectedId(template.id)}
                  onDoubleClick={() => handleSelect(template)}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <h4 className="font-medium truncate">{template.name}</h4>
                        {selectedId === template.id && (
                          <Check className="size-4 text-primary flex-shrink-0" />
                        )}
                      </div>
                      <p className="text-sm text-muted-foreground line-clamp-2 mt-1">
                        {template.message_template}
                      </p>
                      <p className="text-xs text-muted-foreground mt-2">
                        Saved {formatDate(template.created_at)}
                      </p>
                    </div>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="opacity-0 group-hover:opacity-100 flex-shrink-0 text-destructive hover:text-destructive"
                      onClick={(e) => handleDelete(e, template.id)}
                      disabled={deleteMutation.isPending}
                      aria-label="Delete template"
                    >
                      {deleteMutation.isPending ? (
                        <Loader2 className="size-4 animate-spin" />
                      ) : (
                        <Trash2 className="size-4" />
                      )}
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          </ScrollArea>
        )}

        {templates.length > 0 && (
          <div className="flex justify-end gap-2 pt-2 border-t">
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => {
                const template = templates.find((t) => t.id === selectedId);
                if (template) handleSelect(template);
              }}
              disabled={!selectedId}
            >
              Use Template
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
