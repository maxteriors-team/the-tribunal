"use client";

import type { TimelineItem } from "@/types";

import { MessageAttachments } from "./message-attachments";

interface SmsMessageItemProps {
  item: TimelineItem;
}

export function SmsMessageItem({ item }: SmsMessageItemProps) {
  const attachments = item.attachments ?? [];

  return (
    <>
      <MessageAttachments attachments={attachments} />
      {item.content.trim() && (
        <p className="text-sm leading-relaxed whitespace-pre-wrap break-words">
          {item.content}
        </p>
      )}
    </>
  );
}