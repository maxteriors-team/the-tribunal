"use client";

import { Phone, Mail, Building2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { TagBadge } from "@/components/tags/tag-badge";
import { InfoRow } from "@/components/contacts/contact-sidebar/info-row";
import type { Contact } from "@/types";

interface ContactInfoSectionProps {
  contact: Contact;
}

export function ContactInfoSection({ contact }: ContactInfoSectionProps) {
  const tags = Array.isArray(contact.tags)
    ? contact.tags
    : typeof contact.tags === "string"
      ? contact.tags
          .split(",")
          .map((t) => t.trim())
          .filter(Boolean)
      : [];

  const hasTagObjects = !!contact.tag_objects && contact.tag_objects.length > 0;
  const hasStringTags = !hasTagObjects && tags.length > 0;

  return (
    <>
      <div className="space-y-1">
        <h3 className="text-sm font-medium text-muted-foreground px-2 mb-2">
          Contact Info
        </h3>
        <InfoRow
          icon={<Phone className="h-4 w-4 text-muted-foreground" />}
          label="Phone"
          value={contact.phone_number}
          onClick={() =>
            contact.phone_number && window.open(`tel:${contact.phone_number}`)
          }
        />
        <InfoRow
          icon={<Mail className="h-4 w-4 text-muted-foreground" />}
          label="Email"
          value={contact.email}
          onClick={() => contact.email && window.open(`mailto:${contact.email}`)}
        />
        <InfoRow
          icon={<Building2 className="h-4 w-4 text-muted-foreground" />}
          label="Company"
          value={contact.company_name}
        />
      </div>

      {hasTagObjects && (
        <>
          <Separator />
          <div className="space-y-2">
            <h3 className="text-sm font-medium text-muted-foreground px-2">
              Tags
            </h3>
            <div className="flex flex-wrap gap-1.5 px-2">
              {contact.tag_objects!.map((tag) => (
                <TagBadge key={tag.id} name={tag.name} color={tag.color} />
              ))}
            </div>
          </div>
        </>
      )}

      {hasStringTags && (
        <>
          <Separator />
          <div className="space-y-2">
            <h3 className="text-sm font-medium text-muted-foreground px-2">
              Tags
            </h3>
            <div className="flex flex-wrap gap-1.5 px-2">
              {tags.map((tag) => (
                <Badge key={tag} variant="secondary" className="text-xs">
                  {tag}
                </Badge>
              ))}
            </div>
          </div>
        </>
      )}
    </>
  );
}
