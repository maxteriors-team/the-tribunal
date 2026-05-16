"use client";

import type { TimelineItem } from "@/types";

import { InboundMessageItem } from "./inbound-message-item";
import { OutboundMessageItem } from "./outbound-message-item";

interface MessageItemProps {
  item: TimelineItem;
  contactName?: string;
}

export function MessageItem({ item, contactName }: MessageItemProps) {
  if (item.direction === "outbound") {
    return <OutboundMessageItem item={item} contactName={contactName} />;
  }
  return <InboundMessageItem item={item} contactName={contactName} />;
}
