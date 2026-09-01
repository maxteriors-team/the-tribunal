"use client";

import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, Loader2, User } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { MessageComposer } from "@/components/conversation/message-composer";
import { Button } from "@/components/ui/button";
import { PageEmptyState, PageErrorState, PageLoadingState } from "@/components/ui/page-state";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useDeadlinePassed } from "@/hooks/useDeadlinePassed";
import { conversationsApi } from "@/lib/api/conversations";
import { queryKeys } from "@/lib/query-keys";
import { cn } from "@/lib/utils";
import { formatDate } from "@/lib/utils/date";
import { getApiErrorMessage } from "@/lib/utils/errors";
import type { Conversation, Message } from "@/types";
import { CHANNEL_LABELS, MESSENGER_CHANNELS } from "@/types/conversation";

const PAGE_SIZE = 50;

interface MessageThreadDialogProps {
  workspaceId: string;
  conversation: Conversation;
  contactName: string;
}

/**
 * Why this thread cannot be answered here, or null when it can.
 *
 * A composer that accepts text the backend will refuse is worse than no
 * composer: the operator believes the customer was answered.
 */
function replyBlockedReason(conversation: Conversation, windowClosed: boolean): string | null {
  if (MESSENGER_CHANNELS.includes(conversation.channel as (typeof MESSENGER_CHANNELS)[number])) {
    if (!windowClosed) return null;
    return `Reply window closed. ${
      CHANNEL_LABELS[conversation.channel] ?? "This channel"
    } only allows replies for 24 hours after their last message.`;
  }
  // Replies here go out as a text on the thread's own phone pair, so an email
  // thread has no answerable transport and a phoneless thread has no address.
  if (conversation.channel === "email") {
    return "Email threads can't be answered here yet — reply from your email inbox.";
  }
  if (!conversation.contact_phone || !conversation.workspace_phone) {
    return "This thread has no phone number to reply to.";
  }
  return null;
}

/**
 * One thread's history, plus a reply box.
 *
 * Backed by the paginated messages endpoint rather than the conversation
 * detail route: reading an archived thread must not clear its unread badge,
 * and history older than the newest slice has to stay reachable.
 */
export function MessageThreadDialog({
  workspaceId,
  conversation,
  contactName,
}: MessageThreadDialogProps) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState("");
  const [isSending, setIsSending] = useState(false);
  // Quo requires a client request id and dedupes on it, so a retry of the same
  // draft must reuse the id rather than risk texting the customer twice.
  const pendingRequestRef = useRef<{ id: string; body: string } | null>(null);

  const windowClosed = useDeadlinePassed(conversation.messenger_window_expires_at);
  const blockedReason = replyBlockedReason(conversation, windowClosed);

  const handleSend = async () => {
    const body = draft.trim();
    if (!body || isSending) return;

    const pending = pendingRequestRef.current;
    const clientRequestId =
      pending?.body === body ? pending.id : globalThis.crypto.randomUUID();
    setDraft("");
    setIsSending(true);
    try {
      await conversationsApi.sendMessage(workspaceId, conversation.id, body, clientRequestId);
      pendingRequestRef.current = null;
      void queryClient.invalidateQueries({
        queryKey: queryKeys.conversations.messages(workspaceId, conversation.id),
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.conversations.all(workspaceId) });
      toast.success("Message sent");
    } catch (error) {
      setDraft(body);
      pendingRequestRef.current = { id: clientRequestId, body };
      toast.error(getApiErrorMessage(error, "Failed to send message"));
    } finally {
      setIsSending(false);
    }
  };

  return (
    <div className="space-y-3">
      <ThreadHistory
        workspaceId={workspaceId}
        conversationId={conversation.id}
        contactName={contactName}
      />

      {blockedReason ? (
        <p role="status" className="border-t px-4 py-3 text-center text-xs text-muted-foreground">
          {blockedReason}
        </p>
      ) : (
        <MessageComposer
          message={draft}
          onMessageChange={setDraft}
          onSend={handleSend}
          isSending={isSending}
          phoneNumbers={[]}
          selectedFromNumber={conversation.workspace_phone ?? undefined}
          onFromNumberChange={() => {}}
          // The thread's own line is the only sender that keeps the reply in
          // this conversation, and this endpoint takes no attachments.
          textOnly
        />
      )}
    </div>
  );
}

/**
 * Pages walk backwards in time, so they are rendered oldest-first with the
 * newest at the bottom -- the direction a conversation is actually read.
 */
function ThreadHistory({
  workspaceId,
  conversationId,
  contactName,
}: {
  workspaceId: string;
  conversationId: string;
  contactName: string;
}) {
  const { data, isPending, error, fetchNextPage, hasNextPage, isFetchingNextPage } =
    useInfiniteQuery({
      queryKey: queryKeys.conversations.messages(workspaceId, conversationId),
      queryFn: ({ pageParam }) =>
        conversationsApi.listMessages(workspaceId, conversationId, {
          page: pageParam,
          page_size: PAGE_SIZE,
        }),
      initialPageParam: 1,
      getNextPageParam: (lastPage) =>
        lastPage.page < lastPage.pages ? lastPage.page + 1 : undefined,
      enabled: Boolean(workspaceId && conversationId),
    });

  if (isPending) return <PageLoadingState className="h-64" />;

  if (error) {
    return (
      <PageErrorState
        className="h-64"
        message={(error as Error).message || "Failed to load this conversation"}
      />
    );
  }

  // Page 1 is the newest slice, so later pages are older: reverse the pages to
  // put the oldest at the top without re-sorting every message.
  const messages: Message[] = [...(data?.pages ?? [])].reverse().flatMap((page) => page.items);
  const total = data?.pages[0]?.total ?? 0;

  if (messages.length === 0) {
    return (
      <PageEmptyState
        className="py-10"
        title="No messages yet"
        description="This conversation has no message history."
      />
    );
  }

  return (
    <>
      <ScrollArea className="h-[60vh] pr-3">
        {hasNextPage ? (
          <div className="flex justify-center pb-3">
            <Button
              variant="outline"
              size="sm"
              onClick={() => fetchNextPage()}
              disabled={isFetchingNextPage}
            >
              {isFetchingNextPage ? (
                <>
                  <Loader2 className="mr-2 size-4 animate-spin" aria-hidden="true" />
                  Loading older messages
                </>
              ) : (
                "Load older messages"
              )}
            </Button>
          </div>
        ) : null}

        <ol className="space-y-3">
          {messages.map((message) => {
            const outbound = message.direction === "outbound";
            return (
              <li
                key={message.id}
                className={cn("flex", outbound ? "justify-end" : "justify-start")}
              >
                <div
                  className={cn(
                    "max-w-[75%] rounded-lg px-3 py-2",
                    outbound ? "bg-primary/10" : "bg-muted",
                  )}
                >
                  <p className="whitespace-pre-wrap break-words text-sm">{message.body}</p>
                  <p className="mt-1 flex items-center gap-1.5 text-xs text-muted-foreground">
                    {outbound ? (
                      <>
                        {message.is_ai ? (
                          <Bot className="size-3" aria-hidden="true" />
                        ) : (
                          <User className="size-3" aria-hidden="true" />
                        )}
                        <span>{message.is_ai ? "AI" : (message.sender_display_name ?? "Team")}</span>
                      </>
                    ) : (
                      <span>{contactName}</span>
                    )}
                    <span aria-hidden="true">&middot;</span>
                    <time dateTime={message.created_at}>
                      {formatDate(message.created_at, { pattern: "MMM d, yyyy 'at' h:mm a" })}
                    </time>
                  </p>
                </div>
              </li>
            );
          })}
        </ol>
      </ScrollArea>
      <p className="text-center text-xs text-muted-foreground">
        Showing {messages.length} of {total} messages
      </p>
    </>
  );
}
