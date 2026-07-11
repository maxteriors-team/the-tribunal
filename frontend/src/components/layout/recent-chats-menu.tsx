"use client";

import { useQuery } from "@tanstack/react-query";
import { MessagesSquare } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { conversationsApi } from "@/lib/api/conversations";
import { queryKeys } from "@/lib/query-keys";
import { cn } from "@/lib/utils";
import { formatRelative } from "@/lib/utils/date";
import { formatPhoneNumber } from "@/lib/utils/phone";
import type { Conversation } from "@/types";

const RECENT_CHATS_LIMIT = 12;
const RECENT_CHATS_PARAMS = { page: 1, page_size: RECENT_CHATS_LIMIT } as const;

/**
 * Header entry point for customer chats. Opens a menu listing conversations
 * most-recently-updated first (the API already orders by `last_message_at`
 * desc), so operators can jump straight into the freshest threads.
 */
export function RecentChatsMenu() {
  const router = useRouter();
  const workspaceId = useWorkspaceId();
  const [open, setOpen] = useState(false);

  const { data, isPending, isError } = useQuery({
    queryKey: queryKeys.conversations.list(workspaceId ?? "", RECENT_CHATS_PARAMS),
    queryFn: () => conversationsApi.list(workspaceId!, RECENT_CHATS_PARAMS),
    // Only fetch once the menu is opened to avoid a load on every page.
    enabled: open && !!workspaceId,
  });

  const conversations = data?.items ?? [];
  const unreadTotal = conversations.reduce(
    (sum, conversation) => sum + (conversation.unread_count ?? 0),
    0,
  );

  const openConversation = (conversation: Conversation) => {
    setOpen(false);
    if (conversation.contact_id != null) {
      router.push(`/contacts/${conversation.contact_id}`);
    }
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="icon" aria-label="Recent chats">
          <MessagesSquare className="size-4" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 p-0">
        <div className="flex items-center justify-between border-b px-3 py-2.5">
          <span className="text-sm font-medium">Recent chats</span>
          {unreadTotal > 0 ? (
            <Badge variant="secondary">{unreadTotal} unread</Badge>
          ) : null}
        </div>
        <ScrollArea className="max-h-96">
          {isPending && open ? (
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
                <li key={conversation.id}>
                  <button
                    type="button"
                    onClick={() => openConversation(conversation)}
                    disabled={conversation.contact_id == null}
                    className="flex w-full flex-col items-start gap-0.5 px-3 py-2 text-left hover:bg-muted disabled:cursor-not-allowed disabled:opacity-60"
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
                        {formatPhoneNumber(conversation.contact_phone)}
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
                          {conversation.unread_count}
                        </Badge>
                      ) : null}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </ScrollArea>
      </PopoverContent>
    </Popover>
  );
}
