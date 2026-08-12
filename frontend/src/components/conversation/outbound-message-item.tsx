"use client";

import { Calendar, GraduationCap } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { TimelineItem } from "@/types";

import { CallMessageItem } from "./call-message-item";
import { MessageItemShell } from "./message-item-shell";
import { SmsMessageItem } from "./sms-message-item";

interface OutboundMessageItemProps {
  item: TimelineItem;
  contactName?: string;
  onTeachAI?: (item: TimelineItem) => void;
}

export function OutboundMessageItem({ item, contactName, onTeachAI }: OutboundMessageItemProps) {
  return (
    <MessageItemShell item={item} isOutbound={true} contactName={contactName}>
      {item.type === "call" ? (
        <CallMessageItem item={item} isOutbound={true} />
      ) : item.type === "appointment" ? (
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-full bg-info/10 flex items-center justify-center">
            <Calendar className="h-4 w-4 text-info" />
          </div>
          <div className="flex-1">
            <p className="font-medium text-sm">Appointment Scheduled</p>
            <p className="text-xs text-muted-foreground">{item.content}</p>
          </div>
        </div>
      ) : (
        <SmsMessageItem item={item} />
      )}
      {item.type === "sms" && item.is_ai && (
        <div className="mt-1 flex justify-end">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-7 gap-1 px-2 text-xs text-muted-foreground"
            onClick={() => onTeachAI?.(item)}
            disabled={!onTeachAI}
            title={onTeachAI ? undefined : "Assign an agent before teaching this reply"}
            aria-label="Teach AI from this reply"
          >
            <GraduationCap className="size-3.5" />
            Teach AI
          </Button>
        </div>
      )}
    </MessageItemShell>
  );
}
