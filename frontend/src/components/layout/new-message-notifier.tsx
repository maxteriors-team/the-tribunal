"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useRef } from "react";
import { toast } from "sonner";

import {
  useMarkConversationRead,
  useUnreadSummary,
} from "@/hooks/useConversations";
import { recentChatsQueryOptions } from "@/hooks/useRecentChats";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { formatPhoneNumber } from "@/lib/utils/phone";
import type { Conversation } from "@/types";

/** Preview text is operator-facing; long SMS bodies get an ellipsis. */
const PREVIEW_MAX = 120;

/** Operators recognize people, not phone numbers — fall back only when unnamed. */
export function conversationLabel(conversation: Conversation): string {
  return (
    conversation.contact_name?.trim() ||
    formatPhoneNumber(conversation.contact_phone) ||
    "Unknown contact"
  );
}

export function truncatePreview(preview: string | null | undefined): string {
  const text = preview?.trim();
  if (!text) return "New message";
  return text.length > PREVIEW_MAX ? `${text.slice(0, PREVIEW_MAX - 1)}…` : text;
}

/** A thread is "newer" only when its last message timestamp actually advanced. */
function lastMessageTime(conversation: Conversation): number {
  const raw = conversation.last_message_at;
  if (!raw) return 0;
  const parsed = new Date(raw).getTime();
  return Number.isNaN(parsed) ? 0 : parsed;
}

/**
 * Which threads got a new inbound message between two polls.
 *
 * Compares against the previous snapshot rather than "unread > 0" so a thread
 * that stays unread doesn't re-toast on every poll. Threads absent from the
 * previous snapshot are only announced when the notifier has already seen a
 * baseline — otherwise the first load after sign-in would toast the whole
 * inbox at once.
 */
export function findNewInboundMessages(
  previous: Map<string, number> | null,
  current: Conversation[],
): Conversation[] {
  if (previous === null) return [];

  return current.filter((conversation) => {
    if ((conversation.unread_count ?? 0) <= 0) return false;

    const timestamp = lastMessageTime(conversation);
    if (timestamp === 0) return false;

    const seen = previous.get(conversation.id);
    return seen === undefined || timestamp > seen;
  });
}

function snapshot(conversations: Conversation[]): Map<string, number> {
  return new Map(conversations.map((c) => [c.id, lastMessageTime(c)]));
}

/**
 * Toasts inbound customer messages as they arrive, workspace-wide.
 *
 * Mounted once in the app shell, next to the header chat menu. Each toast names
 * the sender, previews the message, and offers the two things an operator does
 * next: open the thread, or clear it without leaving the page.
 *
 * Only the unread rollup is polled, because this is mounted on every page for
 * every operator. The thread list — the expensive request, and the only source
 * of sender names and previews — is fetched on demand, when the rollup says
 * something actually arrived. It lands in the same cache entry the chat menu
 * reads, so opening the menu right after a toast renders instantly.
 *
 * Known gap: if an operator reads one thread and another arrives inside the
 * same poll window, the rollup total can land unchanged and that arrival goes
 * unannounced. The badge still corrects itself on the next poll.
 */
export function NewMessageNotifier() {
  const workspaceId = useWorkspaceId();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { data: unread } = useUnreadSummary(workspaceId);
  // `mutate` is referentially stable, so the toast callbacks can close over it
  // without re-running this effect on every render.
  const { mutate: markRead } = useMarkConversationRead(workspaceId ?? "");

  const unreadTotal = unread?.unread_messages ?? null;

  // `null` until a baseline is established, so a full inbox at sign-in is never
  // announced as if it just arrived.
  const seenRef = useRef<Map<string, number> | null>(null);
  const lastTotalRef = useRef<number | null>(null);
  // Reset the baseline on workspace switch so the new inbox doesn't toast.
  const workspaceRef = useRef(workspaceId);

  useEffect(() => {
    if (workspaceRef.current !== workspaceId) {
      workspaceRef.current = workspaceId;
      seenRef.current = null;
      lastTotalRef.current = null;
    }
  }, [workspaceId]);

  useEffect(() => {
    if (!workspaceId || unreadTotal === null) return;

    const previousTotal = lastTotalRef.current;
    lastTotalRef.current = unreadTotal;

    // An empty inbox is a baseline in itself: nothing is waiting, so the next
    // thread to appear is unambiguously new and needs no list fetch to prove it.
    if (unreadTotal === 0) {
      seenRef.current = new Map();
      return;
    }

    // The rollup didn't grow, so nothing arrived worth spending a fetch on.
    const grew = previousTotal === null || unreadTotal > previousTotal;
    if (!grew && seenRef.current !== null) return;

    let cancelled = false;

    void (async () => {
      let conversations: Conversation[];
      try {
        const result = await queryClient.fetchQuery(
          recentChatsQueryOptions(workspaceId),
        );
        conversations = result.items ?? [];
      } catch {
        // A failed fetch shouldn't break the page or poison the baseline; the
        // next rollup poll retries.
        return;
      }
      if (cancelled) return;

      const arrivals = findNewInboundMessages(seenRef.current, conversations);
      seenRef.current = snapshot(conversations);

      for (const conversation of arrivals) {
        toast.message(conversationLabel(conversation), {
          id: `new-message-${conversation.id}`,
          description: truncatePreview(conversation.last_message_preview),
          duration: 8000,
          action: conversation.contact_id
            ? {
                label: "Open",
                onClick: () => {
                  markRead(conversation.id);
                  router.push(`/contacts/${conversation.contact_id}`);
                },
              }
            : undefined,
          cancel: {
            label: "Mark read",
            onClick: () => markRead(conversation.id),
          },
        });
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [unreadTotal, workspaceId, router, queryClient, markRead]);

  return null;
}
