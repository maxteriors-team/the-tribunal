"use client";

import { Check, CheckCheck, MessagesSquare } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { useCapabilities } from "@/hooks/useCapabilities";
import {
  useMarkAllConversationsRead,
  useMarkConversationRead,
  useUnreadSummary,
} from "@/hooks/useConversations";
import { useRecentChats } from "@/hooks/useRecentChats";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { cn } from "@/lib/utils";
import { formatRelative } from "@/lib/utils/date";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { formatPhoneNumber } from "@/lib/utils/phone";
import type { Conversation } from "@/types";

/** Two digits fit the badge; beyond that the exact number stops mattering. */
const BADGE_MAX = 99;

export function formatUnreadBadge(count: number): string {
  return count > BADGE_MAX ? `${BADGE_MAX}+` : String(count);
}

/**
 * Header entry point for customer chats. Opens a menu listing conversations
 * most-recently-updated first (the API already orders by `last_message_at`
 * desc), so operators can jump straight into the freshest threads.
 *
 * The trigger carries an unread badge sourced from a workspace-wide rollup, not
 * from this menu's page — a page of 12 threads can't see the 13th unread one.
 */
export function RecentChatsMenu() {
  const router = useRouter();
  const workspaceId = useWorkspaceId();
  const [open, setOpen] = useState(false);
  // The conversation list and the unread rollup are both `crm:read`. A field
  // technician has no chat surface — every thread here links to a contact page
  // they cannot open — so the menu is withheld rather than left to 403.
  const { can } = useCapabilities();
  const canReadChats = can("crm:read");
  const chatWorkspaceId = canReadChats ? workspaceId : null;

  // Only fetch once the menu is opened, to avoid a load on every page. The
  // notifier writes this same cache entry when a message arrives, so a
  // just-toasted thread is already here.
  const { data, isPending, isError } = useRecentChats(chatWorkspaceId, {
    enabled: open,
  });
  const { data: unread } = useUnreadSummary(chatWorkspaceId);
  const markRead = useMarkConversationRead(workspaceId ?? "");
  const markAllRead = useMarkAllConversationsRead(workspaceId ?? "");

  const conversations = data?.items ?? [];
  const unreadTotal = unread?.unread_messages ?? 0;
  const unreadThreads = unread?.unread_conversations ?? 0;

  /** Operators recognize people, not phone numbers — fall back only when unnamed. */
  const chatLabel = (conversation: Conversation) =>
    conversation.contact_name?.trim() ||
    formatPhoneNumber(conversation.contact_phone) ||
    "Unknown contact";

  const openConversation = (conversation: Conversation) => {
    setOpen(false);
    if (conversation.unread_count > 0) {
      markRead.mutate(conversation.id);
    }
    if (conversation.contact_id != null) {
      router.push(`/contacts/${conversation.contact_id}`);
    }
  };

  const handleMarkRead = (conversation: Conversation) => {
    markRead.mutate(conversation.id, {
      onError: (err: unknown) => {
        toast.error(getApiErrorMessage(err, "Failed to mark as read"));
      },
    });
  };

  const handleMarkAllRead = () => {
    markAllRead.mutate(undefined, {
      onSuccess: (result) => {
        toast.success(
          result.conversations_marked === 1
            ? "1 conversation marked as read"
            : `${result.conversations_marked} conversations marked as read`,
        );
      },
      onError: (err: unknown) => {
        toast.error(getApiErrorMessage(err, "Failed to mark all as read"));
      },
    });
  };

  if (!canReadChats) return null;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="relative"
          aria-label={
            unreadTotal > 0
              ? `Recent chats, ${unreadTotal} unread`
              : "Recent chats"
          }
        >
          <MessagesSquare className="size-4" />
          {unreadTotal > 0 ? (
            <span
              // aria-hidden: the count is already in the button's accessible
              // name, so screen readers shouldn't hear it twice.
              aria-hidden
              className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[10px] font-semibold leading-none text-primary-foreground"
            >
              {formatUnreadBadge(unreadTotal)}
            </span>
          ) : null}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 p-0">
        <div className="flex items-center justify-between gap-2 border-b px-3 py-2.5">
          <span className="text-sm font-medium">Recent chats</span>
          {unreadThreads > 0 ? (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 gap-1.5 px-2 text-xs"
              onClick={handleMarkAllRead}
              disabled={markAllRead.isPending}
            >
              <CheckCheck className="size-3.5" />
              Mark all read
            </Button>
          ) : null}
        </div>
        <ScrollArea className="max-h-96">
          {isPending ? (
            <div className="space-y-3 p-3">
              {Array.from({ length: 4 }).map((_, index) => (
                <div key={index} className="flex items-center gap-3">
                  <Skeleton className="h-4 w-4 rounded-full" />
                  <div className="flex-1 space-y-1.5">
                    <Skeleton className="h-3 w-32" />
                    <Skeleton className="h-3 w-44" />
                  </div>
                </div>
              ))}
            </div>
          ) : isError ? (
            <p className="px-3 py-6 text-center text-sm text-muted-foreground">
              Could not load chats.
            </p>
          ) : conversations.length === 0 ? (
            <p className="px-3 py-6 text-center text-sm text-muted-foreground">
              No conversations yet.
            </p>
          ) : (
            <ul className="py-1">
              {conversations.map((conversation) => (
                <li key={conversation.id} className="group relative">
                  <button
                    type="button"
                    onClick={() => openConversation(conversation)}
                    disabled={conversation.contact_id == null}
                    // pr-9 reserves the gutter for the mark-read action on
                    // every row, so clearing an unread badge never reflows the
                    // list under the operator's cursor.
                    className="flex w-full flex-col items-start gap-0.5 py-2 pl-3 pr-9 text-left hover:bg-muted disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    <div className="flex w-full items-center justify-between gap-2">
                      <span
                        className={cn(
                          "truncate text-sm",
                          conversation.unread_count > 0
                            ? "font-semibold"
                            : "font-medium",
                        )}
                      >
                        {chatLabel(conversation)}
                      </span>
                      {conversation.last_message_at ? (
                        <span className="shrink-0 text-[11px] text-muted-foreground">
                          {formatRelative(conversation.last_message_at)}
                        </span>
                      ) : null}
                    </div>
                    <div className="flex w-full items-center justify-between gap-2">
                      <span className="truncate text-xs text-muted-foreground">
                        {conversation.last_message_preview ?? "No messages yet"}
                      </span>
                      {conversation.unread_count > 0 ? (
                        <Badge
                          variant="default"
                          className="h-4 shrink-0 px-1.5 text-[10px]"
                        >
                          {formatUnreadBadge(conversation.unread_count)}
                        </Badge>
                      ) : null}
                    </div>
                  </button>
                  {conversation.unread_count > 0 ? (
                    <Button
                      variant="ghost"
                      size="icon"
                      // Hidden until hover/focus so the row stays calm, but
                      // always reachable by keyboard.
                      className="absolute right-1 top-1/2 size-6 -translate-y-1/2 opacity-0 transition-opacity focus-visible:opacity-100 group-hover:opacity-100"
                      aria-label={`Mark ${chatLabel(conversation)} as read`}
                      onClick={() => handleMarkRead(conversation)}
                      disabled={markRead.isPending}
                    >
                      <Check className="size-3.5" />
                    </Button>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </ScrollArea>
      </PopoverContent>
    </Popover>
  );
}
