"use client";

import {
  Phone,
  MessageSquare,
  Mail,
  Voicemail,
  Bot,
  User,
  Calendar,
  FileText,
  ExternalLink,
} from "lucide-react";
import { motion } from "motion/react";
import { type ReactNode } from "react";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { getValidatedQuoLink } from "@/lib/api/quo-links";
import { cn } from "@/lib/utils";
import { formatTime } from "@/lib/utils/date";
import type { TimelineItem } from "@/types";

const channelIcons: Record<string, ReactNode> = {
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
  children: ReactNode;
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
  const isQuoActivity = (item.type === "sms" || isCall) && item.source_provider === "quo";
  const quoLink = isQuoActivity ? getValidatedQuoLink(item) : null;
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
            (contactName?.[0]?.toUpperCase() ?? <User className="h-4 w-4" />)
          )}
        </AvatarFallback>
      </Avatar>

      {/* Message Bubble */}
      <div className={cn("flex flex-col max-w-[70%]", isOutbound ? "items-end" : "items-start")}>
        {/* Sender info */}
        <div
          className={cn(
            "mb-1 flex max-w-full flex-wrap items-center gap-2 text-xs text-muted-foreground",
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
          {isQuoActivity ? (
            <Badge variant="outline" className="h-4 shrink-0 px-1.5 py-0 text-[10px]">
              Quo
            </Badge>
          ) : null}
          <span className="shrink-0">{timestamp}</span>
          <span className="shrink-0" aria-hidden="true">
            {channelIcons[item.type]}
          </span>
          {quoLink ? (
            <a
              href={quoLink}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex shrink-0 items-center gap-1 font-medium text-primary underline-offset-2 hover:underline focus-visible:underline"
            >
              Open in Quo
              <ExternalLink className="h-3 w-3" aria-hidden="true" />
              <span className="sr-only"> (opens in a new tab)</span>
            </a>
          ) : null}
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
