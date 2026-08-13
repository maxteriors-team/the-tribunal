"use client";

import type { TimelineItem } from "@/types";

import { InboundMessageItem } from "./inbound-message-item";
import { OutboundMessageItem } from "./outbound-message-item";

interface MessageItemProps {
  item: TimelineItem;
  contactName?: string;
  onTeachAI?: (item: TimelineItem) => void;
}

export function MessageItem({ item, contactName, onTeachAI }: MessageItemProps) {
  if (item.direction === "outbound") {
    return <OutboundMessageItem item={item} contactName={contactName} onTeachAI={onTeachAI} />;
  }
  return <InboundMessageItem item={item} contactName={contactName} />;
}
