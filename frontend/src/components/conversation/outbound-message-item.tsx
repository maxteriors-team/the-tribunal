"use client";

import { Calendar } from "lucide-react";

import type { TimelineItem } from "@/types";

import { CallMessageItem } from "./call-message-item";
import { MessageItemShell } from "./message-item-shell";
import { SmsMessageItem } from "./sms-message-item";


interface OutboundMessageItemProps {
  item: TimelineItem;
  contactName?: string;
}

export function OutboundMessageItem({ item, contactName }: OutboundMessageItemProps) {
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
    </MessageItemShell>
  );
}
