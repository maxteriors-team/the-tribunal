"use client";

import * as React from "react";
import type { TimelineItem } from "@/types";

interface SmsMessageItemProps {
  item: TimelineItem;
}

export function SmsMessageItem({ item }: SmsMessageItemProps) {
  return (
    <p className="text-sm whitespace-pre-wrap break-words">{item.content}</p>
  );
}
