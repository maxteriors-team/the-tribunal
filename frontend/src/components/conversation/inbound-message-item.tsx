"use client";

import * as React from "react";
import { Calendar } from "lucide-react";
import { MessageItemShell } from "./message-item-shell";
import { CallMessageItem } from "./call-message-item";
import { SmsMessageItem } from "./sms-message-item";
import type { TimelineItem } from "@/types";

interface InboundMessageItemProps {
  item: TimelineItem;
  contactName?: string;
}

export function InboundMessageItem({ item, contactName }: InboundMessageItemProps) {
  return (
    <MessageItemShell item={item} isOutbound={false} contactName={contactName}>
      {item.type === "call" ? (
        <CallMessageItem item={item} isOutbound={false} />
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
