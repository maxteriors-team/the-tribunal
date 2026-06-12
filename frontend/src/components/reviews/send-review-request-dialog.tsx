"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Loader2, Search, Send } from "lucide-react";
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
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useDebounce } from "@/hooks/useDebounce";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { contactsApi } from "@/lib/api/contacts";
import { reviewsApi } from "@/lib/api/reviews";
import { queryKeys } from "@/lib/query-keys";
import { cn } from "@/lib/utils";
import type { Contact } from "@/types";

function contactName(contact: Contact): string {
  const name = [contact.first_name, contact.last_name].filter(Boolean).join(" ");
  return name || contact.email || contact.phone_number || `Contact #${contact.id}`;
}

export function SendReviewRequestDialog() {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();

  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<Contact | null>(null);
  const debouncedSearch = useDebounce(search, 300);

  const { data, isPending: contactsLoading } = useQuery({
    queryKey: queryKeys.contacts.search(workspaceId ?? "", debouncedSearch),
    queryFn: () =>
      contactsApi.list(workspaceId!, {
        search: debouncedSearch || undefined,
        page_size: 20,
      }),
    enabled: !!workspaceId && open,
  });

  const contacts = data?.items ?? [];

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
    setSearch("");
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

        <div className="space-y-3">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder="Search contacts by name, email, phone…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-10"
            />
          </div>

          <div className="h-64 overflow-auto rounded-lg border">
            {contactsLoading ? (
              <div className="flex h-full items-center justify-center text-muted-foreground">
                <Loader2 className="size-6 animate-spin" />
              </div>
            ) : contacts.length === 0 ? (
              <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                No contacts found
              </div>
            ) : (
              <ul className="p-1">
                {contacts.map((contact) => {
                  const isSelected = selected?.id === contact.id;
                  return (
                    <li key={contact.id}>
                      <button
                        type="button"
                        onClick={() => setSelected(contact)}
                        className={cn(
                          "flex w-full items-center justify-between gap-3 rounded-md px-3 py-2 text-left text-sm transition-colors",
                          isSelected ? "bg-primary/10" : "hover:bg-muted/50",
                        )}
                      >
                        <span className="min-w-0">
                          <span className="block truncate font-medium">
                            {contactName(contact)}
                          </span>
                          {contact.phone_number && (
                            <span className="block truncate text-xs text-muted-foreground">
                              {contact.phone_number}
                            </span>
                          )}
                        </span>
                        {isSelected && (
                          <Check className="size-4 shrink-0 text-primary" />
                        )}
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
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
            disabled={!selected || mutation.isPending}
          >
            {mutation.isPending && <Loader2 className="size-4 animate-spin" />}
            Send request
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
