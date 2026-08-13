"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Send } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  ContactPicker,
  contactDisplayName,
} from "@/components/ui/contact-combobox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { reviewsApi } from "@/lib/api/reviews";
import { queryKeys } from "@/lib/query-keys";
import { formatPhoneNumber } from "@/lib/utils/phone";
import type { Contact } from "@/types";

export function SendReviewRequestDialog() {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();

  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<Contact | null>(null);

  const mutation = useMutation({
    mutationFn: (contactId: number) =>
      reviewsApi.createRequest(workspaceId!, {
        contact_id: contactId,
        send_now: true,
      }),
    onSuccess: (result) => {
      // A request row may have been created even when delivery failed
      // (e.g. missing phone number), so always refresh the list.
      queryClient.invalidateQueries({
        queryKey: queryKeys.reviews.requests(workspaceId ?? ""),
      });
      if (result.success) {
        toast.success(result.message || "Review request sent");
        resetAndClose();
      } else {
        toast.error(result.detail || result.message || "Could not send review request");
      }
    },
    onError: () => {
      toast.error("Could not send review request. Please try again.");
    },
  });

  const resetAndClose = () => {
    setOpen(false);
    setSelected(null);
  };

  const handleOpenChange = (next: boolean) => {
    if (mutation.isPending) return;
    if (next) {
      setOpen(true);
    } else {
      resetAndClose();
    }
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button size="sm" className="gap-2">
          <Send className="size-4" />
          Send review request
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Send review request</DialogTitle>
          <DialogDescription>
            Pick a contact to send a review request right now. They&apos;ll get
            the SMS and the request will appear in this list.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-2">
          <Label htmlFor="review-request-contact">Contact</Label>
          <ContactPicker
            id="review-request-contact"
            workspaceId={workspaceId}
            value={selected ? String(selected.id) : ""}
            onChange={(_, contact) => setSelected(contact)}
            placeholder="Search contacts by name, phone, or email…"
            disabled={mutation.isPending}
          />
          {/* The request goes out by SMS, so the number it will reach is the
              one fact worth confirming before sending. */}
          <p className="min-h-5 text-sm text-muted-foreground">
            {selected
              ? selected.phone_number
                ? `Texting ${contactDisplayName(selected)} at ${formatPhoneNumber(selected.phone_number)}.`
                : `${contactDisplayName(selected)} has no phone number, so this request can't be texted.`
              : null}
          </p>
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={resetAndClose}
            disabled={mutation.isPending}
          >
            Cancel
          </Button>
          <Button
            className="gap-2"
            onClick={() => selected && mutation.mutate(selected.id)}
            disabled={!selected || !selected.phone_number || mutation.isPending}
          >
            {mutation.isPending && <Loader2 className="size-4 animate-spin" />}
            Send request
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
