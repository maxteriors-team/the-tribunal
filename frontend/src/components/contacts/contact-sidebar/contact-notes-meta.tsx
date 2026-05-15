"use client";

import { Separator } from "@/components/ui/separator";
import { formatDate } from "@/lib/utils/date";
import type { Contact } from "@/types";

interface ContactNotesMetaProps {
  contact: Contact;
}

const TIMESTAMP_PATTERN = "MMM d, yyyy 'at' h:mm a";

export function ContactNotesMeta({ contact }: ContactNotesMetaProps) {
  return (
    <>
      {contact.notes && (
        <>
          <Separator />
          <div className="space-y-2">
            <h3 className="text-sm font-medium text-muted-foreground px-2">
              Notes
            </h3>
            <div className="bg-muted/50 rounded-lg p-3">
              <p className="text-sm whitespace-pre-wrap">{contact.notes}</p>
            </div>
          </div>
        </>
      )}

      <Separator />
      <div className="space-y-1 px-2 text-xs text-muted-foreground">
        <p>Created: {formatDate(contact.created_at, { pattern: TIMESTAMP_PATTERN })}</p>
        <p>Updated: {formatDate(contact.updated_at, { pattern: TIMESTAMP_PATTERN })}</p>
      </div>
    </>
  );
}
