"use client";

import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";
import Link from "next/link";

import { TagBadge } from "@/components/tags/tag-badge";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { ContactSortBy } from "@/lib/api/contacts";
import { contactStatusDotColors, contactStatusLabels } from "@/lib/status-colors";
import { cn } from "@/lib/utils";
import {
  addDays,
  formatDate,
  formatDayMonth,
  formatTime,
  isToday,
  isYesterday,
} from "@/lib/utils/date";
import type { Contact } from "@/types";

/** Compact mailing address split into two display lines (street / locality). */
export function formatContactAddress(
  contact: Contact,
): { line1: string; line2: string } | null {
  const line1 = [contact.address_line1, contact.address_line2]
    .map((part) => part?.trim())
    .filter(Boolean)
    .join(", ");
  const locality = [contact.address_city, contact.address_state]
    .map((part) => part?.trim())
    .filter(Boolean)
    .join(", ");
  const line2 = [locality, contact.address_zip?.trim()].filter(Boolean).join(" ");
  if (!line1 && !line2) return null;
  return { line1, line2 };
}

/**
 * Jobber-style relative activity label from `last_message_at` (falling back to
 * `updated_at`): today -> time, yesterday -> "Yesterday", within a week ->
 * weekday, otherwise -> "MMM d".
 */
export function formatLastActivity(contact: Contact): string | null {
  const raw = contact.last_message_at ?? contact.updated_at;
  if (!raw) return null;
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return null;
  if (isToday(date)) return formatTime(date);
  if (isYesterday(date)) return "Yesterday";
  if (date >= addDays(new Date(), -7)) return formatDate(date, { pattern: "EEE" });
  return formatDayMonth(date);
}

function ContactTags({ contact }: { contact: Contact }) {
  if (contact.tag_objects && contact.tag_objects.length > 0) {
    return (
      <div className="flex flex-wrap gap-1">
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

  const tagsArray = Array.isArray(contact.tags)
    ? contact.tags
    : typeof contact.tags === "string"
      ? contact.tags.split(",").map((t) => t.trim()).filter(Boolean)
      : [];

  if (tagsArray.length === 0) {
    return <span className="text-muted-foreground">—</span>;
  }

  return (
    <div className="flex flex-wrap gap-1">
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

interface SortHeaderProps {
  label: string;
  active: boolean;
  direction: "asc" | "desc";
  onClick: () => void;
  className?: string;
}

function SortHeader({ label, active, direction, onClick, className }: SortHeaderProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "group/sort hover:text-foreground inline-flex items-center gap-1 uppercase",
        active && "text-foreground",
        className,
      )}
    >
      {label}
      {active ? (
        direction === "asc" ? (
          <ArrowUp className="size-3.5" />
        ) : (
          <ArrowDown className="size-3.5" />
        )
      ) : (
        <ArrowUpDown className="size-3.5 opacity-40 group-hover/sort:opacity-100" />
      )}
    </button>
  );
}

interface ContactRowProps {
  contact: Contact;
  isSelectionMode: boolean;
  isSelected: boolean;
  onSelect: (checked: boolean, shiftKey: boolean) => void;
}

function ContactRow({ contact, isSelectionMode, isSelected, onSelect }: ContactRowProps) {
  const displayName =
    [contact.first_name, contact.last_name].filter(Boolean).join(" ") || "Unknown";
  const address = formatContactAddress(contact);
  const lastActivity = formatLastActivity(contact);
  const hasUnread = (contact.unread_count ?? 0) > 0;

  return (
    <TableRow data-state={isSelected ? "selected" : undefined}>
      {isSelectionMode && (
        <TableCell className="w-10">
          <Checkbox
            checked={isSelected}
            onCheckedChange={(checked) => onSelect(checked === true, false)}
            aria-label={`Select ${displayName}`}
          />
        </TableCell>
      )}
      <TableCell>
        <div className="flex flex-col">
          {isSelectionMode ? (
            <span className="font-semibold">{displayName}</span>
          ) : (
            <Link
              href={`/contacts/${contact.id}`}
              className={cn(
                "hover:text-primary font-semibold transition-colors",
                hasUnread && "text-info",
              )}
            >
              {displayName}
            </Link>
          )}
          {contact.company_name && (
            <span className="text-muted-foreground text-xs">{contact.company_name}</span>
          )}
        </div>
      </TableCell>
      <TableCell className="text-muted-foreground max-w-[220px]">
        {address ? (
          <div className="flex flex-col leading-tight">
            {address.line1 && <span className="truncate text-foreground/80">{address.line1}</span>}
            {address.line2 && <span className="truncate text-xs">{address.line2}</span>}
          </div>
        ) : (
          <span className="text-muted-foreground">—</span>
        )}
      </TableCell>
      <TableCell className="max-w-[200px]">
        <ContactTags contact={contact} />
      </TableCell>
      <TableCell>
        <span className="flex items-center gap-2">
          <span
            className={cn("size-2 shrink-0 rounded-full", contactStatusDotColors[contact.status])}
            aria-hidden
          />
          <span>{contactStatusLabels[contact.status]}</span>
        </span>
      </TableCell>
      <TableCell className="text-muted-foreground text-right tabular-nums">
        {lastActivity ?? "—"}
      </TableCell>
    </TableRow>
  );
}

export interface ContactsTableProps {
  contacts: Contact[];
  sortBy: ContactSortBy;
  onSortByChange: (sort: ContactSortBy) => void;
  isSelectionMode: boolean;
  selectedIds: ReadonlySet<number>;
  onSelectContact: (contactId: number, checked: boolean, shiftKey: boolean) => void;
  allVisibleSelected: boolean;
  someVisibleSelected: boolean;
  onSelectAllVisible: () => void;
}

export function ContactsTable({
  contacts,
  sortBy,
  onSortByChange,
  isSelectionMode,
  selectedIds,
  onSelectContact,
  allVisibleSelected,
  someVisibleSelected,
  onSelectAllVisible,
}: ContactsTableProps) {
  const nameActive = sortBy === "name_asc" || sortBy === "name_desc";
  const activityActive = sortBy === "last_activity_asc" || sortBy === "last_activity_desc";
  const headerChecked = allVisibleSelected
    ? true
    : someVisibleSelected
      ? "indeterminate"
      : false;

  return (
    <div className="rounded-xl border">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            {isSelectionMode && (
              <TableHead className="w-10">
                <Checkbox
                  checked={headerChecked}
                  onCheckedChange={onSelectAllVisible}
                  aria-label="Select all visible contacts"
                />
              </TableHead>
            )}
            <TableHead>
              <SortHeader
                label="Name"
                active={nameActive}
                direction={sortBy === "name_desc" ? "desc" : "asc"}
                onClick={() => onSortByChange(sortBy === "name_asc" ? "name_desc" : "name_asc")}
              />
            </TableHead>
            <TableHead>Address</TableHead>
            <TableHead>Tags</TableHead>
            <TableHead>Status</TableHead>
            <TableHead className="text-right">
              <SortHeader
                label="Last Activity"
                active={activityActive}
                direction={sortBy === "last_activity_asc" ? "asc" : "desc"}
                onClick={() =>
                  onSortByChange(
                    sortBy === "last_activity_desc" ? "last_activity_asc" : "last_activity_desc",
                  )
                }
                className="ml-auto"
              />
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {contacts.map((contact) => (
            <ContactRow
              key={contact.id}
              contact={contact}
              isSelectionMode={isSelectionMode}
              isSelected={selectedIds.has(contact.id)}
              onSelect={(checked, shiftKey) => onSelectContact(contact.id, checked, shiftKey)}
            />
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

export function ContactsTableSkeleton({ rows = 8 }: { rows?: number }) {
  return (
    <div className="rounded-xl border">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead>Name</TableHead>
            <TableHead>Address</TableHead>
            <TableHead>Tags</TableHead>
            <TableHead>Status</TableHead>
            <TableHead className="text-right">Last Activity</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {Array.from({ length: rows }).map((_, i) => (
            <TableRow key={i} className="hover:bg-transparent">
              <TableCell>
                <Skeleton className="h-4 w-32" />
              </TableCell>
              <TableCell>
                <Skeleton className="h-4 w-40" />
              </TableCell>
              <TableCell>
                <Skeleton className="h-4 w-24" />
              </TableCell>
              <TableCell>
                <Skeleton className="h-4 w-20" />
              </TableCell>
              <TableCell className="text-right">
                <Skeleton className="ml-auto h-4 w-16" />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
