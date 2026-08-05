"use client";

import { useDraggable } from "@dnd-kit/core";
import {
  CalendarClock,
  CalendarPlus,
  MessageSquare,
  MoreVertical,
  Phone,
  Receipt,
  TimerReset,
  User,
} from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  closeDateLabel,
  closeDateStatus,
  daysInStage,
  formatSourceLabel,
  lineItemsTotal,
  STALE_STAGE_DAYS,
} from "@/lib/opportunities/card-details";
import { contactStatusDotColors, contactStatusLabels } from "@/lib/status-colors";
import { cn } from "@/lib/utils";
import { formatCurrency } from "@/lib/utils/number";
import { formatPhoneNumber } from "@/lib/utils/phone";
import type { ContactStatus, Opportunity, OpportunityContact, PipelineStage } from "@/types";

interface OpportunityCardProps {
  opportunity: Opportunity;
  stages: PipelineStage[];
  onOpen: (opportunityId: string) => void;
  onMove: (opportunityId: string, stageId: string) => void;
  onCall: (opportunity: Opportunity) => void;
  onSchedule: (opportunity: Opportunity) => void;
  onRemove: (opportunity: Opportunity) => void;
}

export function OpportunityCard({
  opportunity,
  stages,
  onOpen,
  onMove,
  onCall,
  onSchedule,
  onRemove,
}: OpportunityCardProps) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: opportunity.id,
  });
  const contact = opportunity.primary_contact ?? null;

  return (
    <div
      ref={setNodeRef}
      className={cn(
        "group/card relative rounded-md border bg-background shadow-sm transition-colors",
        // `has-[:focus-visible]` rather than `focus-within`: a mouse click on a
        // quick action leaves that button focused, and focus-within would strand
        // the card in a highlighted state that reads as "selected".
        "hover:border-primary/50 has-[:focus-visible]:border-primary/60",
        isDragging && "opacity-50"
      )}
      data-testid={`opportunity-card-${opportunity.id}`}
    >
      {/*
        Only this region carries the drag listeners, so the quick actions below
        stay clickable and a pointer-drag never starts from them.
      */}
      <button
        type="button"
        className="w-full cursor-pointer rounded-t-md px-3 pb-2 pt-3 text-left outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
        onClick={() => onOpen(opportunity.id)}
        {...attributes}
        {...listeners}
      >
        <OpportunityCardSummary opportunity={opportunity} />
      </button>

      {contact ? (
        <OpportunityQuickActions
          contact={contact}
          onCall={() => onCall(opportunity)}
          onSchedule={() => onSchedule(opportunity)}
        />
      ) : null}

      <div className="absolute right-1.5 top-1.5">
        <DropdownMenu>
          <DropdownMenuTrigger
            className="rounded p-1 text-muted-foreground outline-none transition-colors hover:bg-muted hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50"
            aria-label={`Actions for ${opportunity.name}`}
          >
            <MoreVertical className="h-4 w-4" aria-hidden />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onClick={() => onOpen(opportunity.id)}>
              Open deal
            </DropdownMenuItem>
            {contact ? (
              <DropdownMenuItem asChild>
                <Link href={`/contacts/${contact.id}/details`}>View contact</Link>
              </DropdownMenuItem>
            ) : null}
            <DropdownMenuSeparator />
            {/* Keyboard-accessible equivalent of the pointer-only drag. */}
            <DropdownMenuLabel>Move to</DropdownMenuLabel>
            {stages
              .filter((s) => s.id !== opportunity.stage_id)
              .map((stage) => (
                <DropdownMenuItem
                  key={stage.id}
                  onClick={() => onMove(opportunity.id, stage.id)}
                >
                  {stage.name}
                </DropdownMenuItem>
              ))}
            <DropdownMenuSeparator />
            <DropdownMenuItem
              variant="destructive"
              onClick={() => onRemove(opportunity)}
            >
              Remove from pipeline
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  );
}

/**
 * Read-only card face. Also rendered inside the drag overlay, which sits
 * outside the board's DOM — so it must not depend on drag or dialog state.
 */
export function OpportunityCardSummary({
  opportunity,
  dragging,
}: {
  opportunity: Opportunity;
  dragging?: boolean;
}) {
  const contact = opportunity.primary_contact ?? null;
  const stageAge = daysInStage(opportunity);
  const closeDate = closeDateStatus(opportunity);
  const closeLabel = closeDateLabel(opportunity);
  const itemsTotal = lineItemsTotal(opportunity);
  const itemCount = opportunity.line_items?.length ?? 0;
  const isStale = stageAge !== null && stageAge >= STALE_STAGE_DAYS;
  // A deal that landed today has no aging story worth a line on every card.
  const showStageAge = stageAge !== null && stageAge >= 1;

  return (
    <div className={cn("space-y-2", dragging && "w-64 rounded-md border bg-background p-3 shadow-md")}>
      <div className="pr-6">
        <p className="line-clamp-2 text-sm font-medium leading-snug">{opportunity.name}</p>
      </div>

      {contact ? (
        <div className="space-y-0.5">
          <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <User className="size-3 shrink-0" aria-hidden />
            <span className="truncate text-foreground">{contact.full_name}</span>
            <ContactStatusDot status={contact.status} />
          </p>
          {contact.phone_number ? (
            <p className="pl-[1.125rem] text-xs tabular-nums text-muted-foreground">
              {formatPhoneNumber(contact.phone_number)}
            </p>
          ) : null}
        </div>
      ) : (
        <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <User className="size-3 shrink-0" aria-hidden />
          No contact linked
        </p>
      )}

      <div className="flex items-baseline justify-between gap-2">
        {opportunity.amount != null ? (
          <span className="text-sm font-semibold">
            {formatCurrency(opportunity.amount, opportunity.currency)}
          </span>
        ) : (
          <span className="text-sm text-muted-foreground">No value set</span>
        )}
        <span className="text-xs text-muted-foreground">{opportunity.probability}%</span>
      </div>

      {closeDate && closeLabel ? (
        <p
          className={cn(
            "flex items-center gap-1.5 text-xs",
            closeDate.tone === "overdue"
              ? "font-medium text-destructive"
              : "text-muted-foreground"
          )}
        >
          <CalendarClock className="size-3 shrink-0" aria-hidden />
          {closeLabel}
        </p>
      ) : null}

      {showStageAge ? (
        <p
          className={cn(
            "flex items-center gap-1.5 text-xs",
            isStale ? "font-medium text-foreground" : "text-muted-foreground"
          )}
        >
          <TimerReset className="size-3 shrink-0" aria-hidden />
          {`${stageAge}d in stage`}
          {isStale ? " · needs a nudge" : ""}
        </p>
      ) : null}

      {itemCount > 0 || opportunity.source ? (
        <div className="flex flex-wrap items-center gap-1.5 pt-0.5">
          {opportunity.source ? (
            <Badge variant="outline" className="font-normal">
              {formatSourceLabel(opportunity.source)}
            </Badge>
          ) : null}
          {itemCount > 0 ? (
            <Badge variant="outline" className="font-normal">
              <Receipt className="size-3" aria-hidden />
              {itemCount} {itemCount === 1 ? "item" : "items"}
              {itemsTotal != null
                ? ` · ${formatCurrency(itemsTotal, opportunity.currency)}`
                : ""}
            </Badge>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function ContactStatusDot({ status }: { status: string }) {
  const dotClass = contactStatusDotColors[status as ContactStatus];
  const label = contactStatusLabels[status as ContactStatus];
  if (!dotClass || !label) return null;
  return (
    <>
      <span className={cn("size-1.5 shrink-0 rounded-full", dotClass)} aria-hidden />
      <span className="sr-only">Lead status: </span>
      <span className="shrink-0">{label}</span>
    </>
  );
}

/**
 * Click-to-call and the two follow-ups an operator reaches for next, without
 * opening the deal. Rendered only when a contact is linked — every action here
 * needs one.
 */
function OpportunityQuickActions({
  contact,
  onCall,
  onSchedule,
}: {
  contact: OpportunityContact;
  onCall: () => void;
  onSchedule: () => void;
}) {
  const hasPhone = Boolean(contact.phone_number);

  return (
    <div className="flex items-center gap-1 border-t px-1.5 py-1.5">
      <Button
        variant="ghost"
        size="sm"
        className="h-7 flex-1 px-1.5 text-xs"
        onClick={onCall}
        disabled={!hasPhone}
        aria-label={
          hasPhone
            ? `Call ${contact.full_name}`
            : `Call ${contact.full_name} — no phone number on file`
        }
        data-testid={`opportunity-call-${contact.id}`}
      >
        <Phone className="size-3.5" aria-hidden />
        Call
      </Button>
      <Button variant="ghost" size="sm" className="h-7 flex-1 px-1.5 text-xs" asChild>
        <Link href={`/contacts/${contact.id}`} aria-label={`Text ${contact.full_name}`}>
          <MessageSquare className="size-3.5" aria-hidden />
          Text
        </Link>
      </Button>
      <Button
        variant="ghost"
        size="sm"
        className="h-7 flex-1 px-1.5 text-xs"
        onClick={onSchedule}
        aria-label={`Book an appointment with ${contact.full_name}`}
      >
        <CalendarPlus className="size-3.5" aria-hidden />
        Book
      </Button>
    </div>
  );
}
