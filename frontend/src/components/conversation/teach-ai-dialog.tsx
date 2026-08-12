"use client";

import { useMutation } from "@tanstack/react-query";
import { useId, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { conversationsApi } from "@/lib/api/conversations";
import { getApiErrorMessage } from "@/lib/utils/errors";

interface TeachAIDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  workspaceId: string;
  conversationId: string;
  sourceMessageId: string;
  customerMessage: string;
  aiResponse: string;
  onSaved: (agentName: string) => void;
}

export function TeachAIDialog({
  open,
  onOpenChange,
  workspaceId,
  conversationId,
  sourceMessageId,
  customerMessage,
  aiResponse,
  onSaved,
}: TeachAIDialogProps) {
  const idealId = useId();
  const noteId = useId();
  const [idealResponse, setIdealResponse] = useState("");
  const [note, setNote] = useState("");

  const saveMutation = useMutation({
    mutationFn: () =>
      conversationsApi.teachAI(workspaceId, conversationId, {
        source_message_id: sourceMessageId,
        ideal_response: idealResponse.trim(),
        note: note.trim() || undefined,
      }),
    onSuccess: (saved) => {
      onSaved(saved.agent_name);
      setIdealResponse("");
      setNote("");
      onOpenChange(false);
    },
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Teach AI</DialogTitle>
          <DialogDescription>
            Save an approved example for future replies from the assigned agent. This does not send
            anything to this customer and does not retrain the base model.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-1">
            <Label>Prior customer message</Label>
            <div
              className="rounded-md border bg-muted/40 p-3 text-sm"
              aria-label="Prior customer message"
            >
              {customerMessage}
            </div>
          </div>
          <div className="space-y-1">
            <Label>AI reply</Label>
            <div className="rounded-md border bg-muted/40 p-3 text-sm" aria-label="AI reply">
              {aiResponse}
            </div>
          </div>
          <div className="space-y-1">
            <Label htmlFor={idealId}>What should the AI have said?</Label>
            <Textarea
              id={idealId}
              value={idealResponse}
              onChange={(event) => setIdealResponse(event.target.value)}
              maxLength={1000}
              className="min-h-24"
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor={noteId}>What should it learn? (optional)</Label>
            <Textarea
              id={noteId}
              value={note}
              onChange={(event) => setNote(event.target.value)}
              maxLength={1000}
              className="min-h-20"
            />
          </div>
          {saveMutation.isError && (
            <p role="alert" className="text-sm text-destructive">
              {getApiErrorMessage(saveMutation.error, "Could not save this correction")}
            </p>
          )}
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => {
              setIdealResponse("");
              setNote("");
              onOpenChange(false);
            }}
          >
            Cancel
          </Button>
          <Button
            onClick={() => saveMutation.mutate()}
            disabled={!idealResponse.trim() || saveMutation.isPending}
          >
            {saveMutation.isPending ? "Saving…" : "Save lesson"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
