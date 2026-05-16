"use client";

import { Phone, Mail } from "lucide-react";
import { motion } from "motion/react";
import Link from "next/link";
import { type MouseEvent } from "react";

import { TagBadge } from "@/components/tags/tag-badge";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Skeleton } from "@/components/ui/skeleton";
import { contactStatusColors, contactStatusLabels } from "@/lib/status-colors";
import { cn } from "@/lib/utils";
import { getContactInitials } from "@/lib/utils/initials";
import { formatPhoneNumber } from "@/lib/utils/phone";
import type { Contact } from "@/types";

export function ContactCardSkeleton() {
  return (
    <div className="flex flex-col p-4 rounded-xl border bg-card">
      <div className="flex items-start gap-3">
        <Skeleton className="h-12 w-12 rounded-full" />
        <div className="flex-1 space-y-2">
          <Skeleton className="h-5 w-32" />
          <Skeleton className="h-4 w-24" />
        </div>
      </div>
      <div className="mt-3 space-y-2">
        <Skeleton className="h-3 w-full" />
        <Skeleton className="h-3 w-3/4" />
      </div>
    </div>
  );
}

export interface ContactCardProps {
  contact: Contact;
  isSelected: boolean;
  onSelectChange: (checked: boolean, shiftKey: boolean) => void;
  isSelectionMode: boolean;
}

export function ContactCard({ contact, isSelected, onSelectChange, isSelectionMode }: ContactCardProps) {
  const displayName = [contact.first_name, contact.last_name].filter(Boolean).join(" ") || "Unknown";
  const hasUnread = (contact.unread_count ?? 0) > 0;

  const handleCheckboxClick = (e: MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    onSelectChange(!isSelected, e.shiftKey);
  };

  const cardContent = (
    <motion.div
      layout
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.95 }}
      transition={{ type: "spring", stiffness: 300, damping: 24 }}
      className={cn(
        "flex flex-col p-4 rounded-xl border bg-card card-interactive",
        "hover:bg-accent/50 hover:border-accent transition-all cursor-pointer",
        "group",
        isSelected && "ring-2 ring-primary border-primary bg-primary/5",
        hasUnread && !isSelected && "border-l-4 border-l-info"
      )}
    >
      <div className="flex items-start gap-3">
        {isSelectionMode && (
          // Wrapper exists solely to stop click events from bubbling to the
          // outer card/link. Keyboard activation is handled by the Checkbox
          // itself, so no keyboard listener is needed on the wrapper.
          // eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-static-element-interactions
          <div className="shrink-0 pt-1" onClick={handleCheckboxClick}>
            <Checkbox
              checked={isSelected}
              onCheckedChange={(checked) => onSelectChange(checked === true, false)}
            />
          </div>
        )}
        <div className="relative">
          <Avatar className="h-12 w-12 shrink-0">
            <AvatarImage src={contact.avatar_url} alt={displayName} size={96} />
            <AvatarFallback className="bg-primary/10 text-primary text-base font-medium">
              {getContactInitials(contact)}
            </AvatarFallback>
          </Avatar>
          {hasUnread && (
            <span className="absolute -top-1 -right-1 flex h-5 w-5 items-center justify-center rounded-full bg-info text-[10px] font-bold text-white">
              {contact.unread_count}
            </span>
          )}
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-2">
            <span className={cn(
              "font-semibold truncate group-hover:text-primary transition-colors",
              hasUnread && "text-info"
            )}>
              {displayName}
            </span>
            <Badge variant="secondary" className={cn("text-xs shrink-0", contactStatusColors[contact.status])}>
              {contactStatusLabels[contact.status]}
            </Badge>
          </div>
          {contact.company_name && (
            <p className="text-sm text-muted-foreground truncate mt-0.5">
              {contact.company_name}
            </p>
          )}
        </div>
      </div>

      <div className="mt-3 flex flex-col gap-1.5 text-sm text-muted-foreground">
        {contact.phone_number && (
          <div className="flex items-center gap-2 truncate">
            <Phone className="h-3.5 w-3.5 shrink-0" />
            <span className="truncate">{formatPhoneNumber(contact.phone_number)}</span>
          </div>
        )}
        {contact.email && (
          <div className="flex items-center gap-2 truncate">
            <Mail className="h-3.5 w-3.5 shrink-0" />
            <span className="truncate">{contact.email}</span>
          </div>
        )}
      </div>

      {(() => {
        // Prefer tag_objects (colored) from new system, fall back to legacy string tags
        if (contact.tag_objects && contact.tag_objects.length > 0) {
          return (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {contact.tag_objects.slice(0, 3).map((tag) => (
                <TagBadge key={tag.id} name={tag.name} color={tag.color} />
              ))}
              {contact.tag_objects.length > 3 && (
                <Badge variant="outline" className="text-xs">
                  +{contact.tag_objects.length - 3}
                </Badge>
              )}
            </div>
          );
        }
        if (contact.tags) {
          const tagsArray = Array.isArray(contact.tags)
            ? contact.tags
            : typeof contact.tags === "string"
              ? contact.tags.split(",").map((t) => t.trim()).filter(Boolean)
              : [];
          if (tagsArray.length > 0) {
            return (
              <div className="mt-3 flex flex-wrap gap-1.5">
                {tagsArray.slice(0, 3).map((tag) => (
                  <Badge key={tag} variant="outline" className="text-xs">
                    {tag}
                  </Badge>
                ))}
                {tagsArray.length > 3 && (
                  <Badge variant="outline" className="text-xs">
                    +{tagsArray.length - 3}
                  </Badge>
                )}
              </div>
            );
          }
        }
        return null;
      })()}
    </motion.div>
  );

  if (isSelectionMode) {
    return (
      <div
        role="button"
        tabIndex={0}
        aria-pressed={isSelected}
        onClick={(e) => onSelectChange(!isSelected, e.shiftKey)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onSelectChange(!isSelected, e.shiftKey);
          }
        }}
      >
        {cardContent}
      </div>
    );
  }

  return <Link href={`/contacts/${contact.id}`}>{cardContent}</Link>;
}
