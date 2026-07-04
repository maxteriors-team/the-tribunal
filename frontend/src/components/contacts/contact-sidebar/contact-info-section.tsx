"use client";

import { Phone, Mail, Building2, MapPin } from "lucide-react";

import { InfoRow } from "@/components/contacts/contact-sidebar/info-row";
import { TagBadge } from "@/components/tags/tag-badge";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
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

  // "line1, line2, City, ST 12345" — skip whatever's missing.
  const cityStateZip = [
    contact.address_city,
    [contact.address_state, contact.address_zip].filter(Boolean).join(" "),
  ]
    .filter(Boolean)
    .join(", ");
  const address = [contact.address_line1, contact.address_line2, cityStateZip]
    .filter(Boolean)
    .join(", ");

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
        <InfoRow
          icon={<MapPin className="h-4 w-4 text-muted-foreground" />}
          label="Address"
          value={address || null}
          onClick={() =>
            address &&
            window.open(
              `https://maps.google.com/?q=${encodeURIComponent(address)}`,
              "_blank",
              "noopener,noreferrer"
            )
          }
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
