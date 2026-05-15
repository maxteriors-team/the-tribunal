"use client";

import * as React from "react";
import { motion } from "motion/react";
import {
  Phone,
  MessageSquare,
  Mail,
  Voicemail,
  Bot,
  User,
  Calendar,
  FileText,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { formatTime } from "@/lib/utils/date";
import type { TimelineItem } from "@/types";

const channelIcons: Record<string, React.ReactNode> = {
  sms: <MessageSquare className="h-4 w-4" />,
  call: <Phone className="h-4 w-4" />,
  email: <Mail className="h-4 w-4" />,
  voicemail: <Voicemail className="h-4 w-4" />,
  appointment: <Calendar className="h-4 w-4" />,
  note: <FileText className="h-4 w-4" />,
};

interface MessageItemShellProps {
  item: TimelineItem;
  isOutbound: boolean;
  contactName?: string;
  children: React.ReactNode;
}

/**
 * Shared visual shell for inbound/outbound message items.
 * Internal to the conversation module — consumers should use
 * `<InboundMessageItem>` / `<OutboundMessageItem>` instead.
 */
export function MessageItemShell({
  item,
  isOutbound,
  contactName,
  children,
}: MessageItemShellProps) {
  const isCall = item.type === "call";
  const isAppointment = item.type === "appointment";
  const timestamp = formatTime(item.timestamp);

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className={cn(
        "flex gap-3 px-4 py-2 overflow-hidden",
        isOutbound ? "flex-row-reverse" : "flex-row",
      )}
    >
      {/* Avatar */}
      <Avatar className="h-8 w-8 shrink-0">
        <AvatarFallback
          className={cn(
            "text-xs",
            item.is_ai
              ? "bg-primary/10 text-primary"
              : isOutbound
                ? "bg-primary/10 text-primary"
                : "bg-muted",
          )}
        >
          {item.is_ai ? (
            <Bot className="h-4 w-4" />
          ) : isOutbound ? (
            "You"
          ) : (
            contactName?.[0]?.toUpperCase() ?? <User className="h-4 w-4" />
          )}
        </AvatarFallback>
      </Avatar>

      {/* Message Bubble */}
      <div
        className={cn(
          "flex flex-col max-w-[70%]",
          isOutbound ? "items-end" : "items-start",
        )}
      >
        {/* Sender info */}
        <div
          className={cn(
            "flex items-center gap-2 mb-1 text-xs text-muted-foreground overflow-hidden",
            isOutbound ? "flex-row-reverse" : "flex-row",
          )}
        >
          {item.is_ai && (
            <Badge
              variant="secondary"
              className="text-[10px] px-1.5 py-0 h-4 bg-primary/10 text-primary shrink-0"
            >
              AI
            </Badge>
          )}
          <span className="shrink-0">{timestamp}</span>
          <span className="shrink-0">{channelIcons[item.type]}</span>
        </div>

        {/* Content bubble */}
        <div
          className={cn(
            "rounded-2xl px-4 py-2.5",
            isCall || isAppointment
              ? "bg-muted/50 border"
              : isOutbound
                ? "bg-primary text-primary-foreground"
                : "bg-muted",
          )}
        >
          {children}
        </div>
      </div>
    </motion.div>
  );
}
