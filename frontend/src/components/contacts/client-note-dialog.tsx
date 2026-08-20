"use client";

import { Loader2 } from "lucide-react";
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
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useAppendContactNote } from "@/hooks/useContacts";
import { getApiErrorMessage } from "@/lib/utils/errors";

interface ClientNoteDialogProps {
  workspaceId: string;
  contactId: number;
  contactName?: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const MAX_NOTE_LENGTH = 5000;

export function ClientNoteDialog({
  workspaceId,
  contactId,
  contactName,
  open,
  onOpenChange,
}: ClientNoteDialogProps) {
  const [body, setBody] = useState("");
  const appendNote = useAppendContactNote(workspaceId, contactId);

  const trimmedBody = body.trim();

  const handleSave = () => {
    if (!trimmedBody) return;
    appendNote.mutate(
      { body: trimmedBody },
      {
        onSuccess: () => {
          toast.success("Client note saved");
          onOpenChange(false);
        },
        onError: (error) => {
          toast.error(getApiErrorMessage(error, "Client note could not be saved"));
        },
      },
    );
  };

  const handleOpenChange = (nextOpen: boolean) => {
    if (!nextOpen) setBody("");
    onOpenChange(nextOpen);
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Add client note</DialogTitle>
          <DialogDescription>
            Add an internal note{contactName ? ` for ${contactName}` : ""}. It is visible only to
            authorized workspace members.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <div className="flex items-center justify-between gap-3">
            <Label htmlFor={`client-note-${contactId}`}>Note</Label>
            <span className="text-xs text-muted-foreground" aria-live="polite">
              {body.length}/{MAX_NOTE_LENGTH}
            </span>
          </div>
          <Textarea
            id={`client-note-${contactId}`}
            value={body}
            maxLength={MAX_NOTE_LENGTH}
            rows={6}
            placeholder="Add details the team should know about this client"
            onChange={(event) => setBody(event.target.value)}
          />
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => handleOpenChange(false)}>
            Cancel
          </Button>
          <Button
            type="button"
            onClick={handleSave}
            disabled={!trimmedBody || appendNote.isPending}
          >
            {appendNote.isPending && <Loader2 className="mr-2 size-4 animate-spin" />}
            Save note
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
