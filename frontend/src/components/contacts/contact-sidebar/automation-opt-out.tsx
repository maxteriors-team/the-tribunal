"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { BellOff } from "lucide-react";
import { toast } from "sonner";

import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { contactsApi } from "@/lib/api/contacts";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";
import type { Contact } from "@/types";

/**
 * Reserved tag name. Must match
 * `backend/app/services/automations/opt_out.py::NO_AUTOMATION_TAG`.
 */
export const NO_AUTOMATION_TAG = "no-automation";

/** Tag names on a contact, tolerating the legacy comma-string shape. */
export function contactTagNames(contact: Contact): string[] {
  if (contact.tag_objects?.length) {
    return contact.tag_objects.map((tag) => tag.name);
  }
  if (Array.isArray(contact.tags)) return contact.tags;
  if (typeof contact.tags === "string") {
    return contact.tags
      .split(",")
      .map((tag) => tag.trim())
      .filter(Boolean);
  }
  return [];
}

export function hasNoAutomationTag(contact: Contact): boolean {
  return contactTagNames(contact).some(
    (name) => name.toLowerCase() === NO_AUTOMATION_TAG,
  );
}

/**
 * The per-customer automation kill switch.
 *
 * One tag turns off *automated* outreach and automated pipeline movement for
 * this contact — the copy names both, because an operator switching this on
 * needs to know it does not also stop them texting the customer themselves.
 * Implemented as a tag rather than a column so it is visible on the contact,
 * filterable in lists, and honoured by one backend check.
 */
export function AutomationOptOut({
  contact,
  workspaceId,
}: {
  contact: Contact;
  workspaceId: string;
}) {
  const queryClient = useQueryClient();
  const suppressed = hasNoAutomationTag(contact);

  const mutation = useMutation({
    mutationFn: (nextSuppressed: boolean) => {
      const current = contactTagNames(contact);
      const tags = nextSuppressed
        ? [...current, NO_AUTOMATION_TAG]
        : current.filter((name) => name.toLowerCase() !== NO_AUTOMATION_TAG);
      return contactsApi.update(workspaceId, contact.id, { tags });
    },
    onSuccess: (_data, nextSuppressed) => {
      toast.success(
        nextSuppressed
          ? "Automation paused for this contact"
          : "Automation resumed for this contact",
      );
    },
    onError: (error) =>
      toast.error(getApiErrorMessage(error, "Couldn't update automation")),
    onSettled: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.contacts.all(workspaceId),
      });
    },
  });

  return (
    <div className="space-y-2 px-2">
      <div className="flex items-start justify-between gap-3">
        <Label
          htmlFor={`no-automation-${contact.id}`}
          className="flex items-center gap-1.5 text-sm font-medium"
        >
          <BellOff className="size-4 text-muted-foreground" aria-hidden />
          Pause automation
        </Label>
        <Switch
          id={`no-automation-${contact.id}`}
          checked={suppressed}
          onCheckedChange={(next) => mutation.mutate(next)}
          disabled={mutation.isPending}
        />
      </div>
      <p className="text-xs text-muted-foreground">
        {suppressed
          ? "Automated follow-ups and automatic pipeline moves are off for this contact. You can still call, text, and move their deal yourself."
          : "Adds the no-automation tag: no automated follow-ups and no automatic pipeline moves for this contact. Anything you do by hand still works."}
      </p>
    </div>
  );
}
