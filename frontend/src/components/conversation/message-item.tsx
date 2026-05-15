"use client";

import * as React from "react";
import { InboundMessageItem } from "./inbound-message-item";
import { OutboundMessageItem } from "./outbound-message-item";
import type { TimelineItem } from "@/types";

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
