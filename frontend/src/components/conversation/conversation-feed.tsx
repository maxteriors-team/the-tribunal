"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { MessageSquare } from "lucide-react";
import { AnimatePresence } from "motion/react";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { PageEmptyState, PageErrorState } from "@/components/ui/page-state";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { useAgents } from "@/hooks/useAgents";
import { useContactTimeline } from "@/hooks/useContacts";
import {
  useToggleConversationAI,
  useAssignAgent,
  useClearConversationHistory,
  useMarkConversationRead,
} from "@/hooks/useConversations";
import { useDeadlinePassed } from "@/hooks/useDeadlinePassed";
import { usePhoneNumbers } from "@/hooks/usePhoneNumbers";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { conversationsApi } from "@/lib/api/conversations";
import { useContactStore } from "@/lib/contact-store";
import { queryKeys } from "@/lib/query-keys";
import { cn } from "@/lib/utils";
import { isSameDay } from "@/lib/utils/date";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { normalizePhoneForComparison } from "@/lib/utils/phone";
import type { Contact, Conversation, TimelineItem } from "@/types";
import { CHANNEL_LABELS } from "@/types/conversation";

import { ChatHeader } from "./chat-header";
import { DateSeparator } from "./date-separator";
import { MessageComposer } from "./message-composer";
import { MessageItem } from "./message-item";
import { TeachAIDialog } from "./teach-ai-dialog";

interface ConversationFeedProps {
  className?: string;
  contact?: Contact | null;
}

function LoadingSkeleton() {
  return (
    <div className="space-y-4 p-4">
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className={cn("flex gap-3", i % 2 === 0 ? "flex-row" : "flex-row-reverse")}>
          <Skeleton className="h-8 w-8 rounded-full shrink-0" />
          <Skeleton className={cn("h-16 rounded-2xl", i % 2 === 0 ? "w-48" : "w-64")} />
        </div>
      ))}
    </div>
  );
}

export function ConversationFeed({ className, contact }: ConversationFeedProps) {
  const { selectedContact: storedContact } = useContactStore();
  const selectedContact = contact === undefined ? storedContact : contact;
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();

  const [message, setMessage] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [selectedFromNumber, setSelectedFromNumber] = useState<string | undefined>();
  const scrollAreaRef = useRef<HTMLDivElement>(null);
  const [teachAIMessage, setTeachAIMessage] = useState<TimelineItem | null>(null);

  const { data: phoneNumbersData } = usePhoneNumbers(workspaceId ?? "", {
    sms_enabled: true,
    active_only: true,
  });
  const phoneNumbers = useMemo(() => phoneNumbersData?.items ?? [], [phoneNumbersData?.items]);
  const fallbackFromNumber = phoneNumbers[0]?.phone_number;


  const { data: agentsData } = useAgents(workspaceId ?? "");
  const agents = useMemo(() => agentsData?.items ?? [], [agentsData?.items]);

  const { data: conversationsData, isPending: isConversationsPending } = useQuery({
    queryKey: queryKeys.conversations.byContact(workspaceId ?? "", selectedContact?.id),
    queryFn: () =>
      workspaceId
        ? conversationsApi.list(workspaceId, { page: 1, page_size: 100 })
        : Promise.resolve({
            items: [],
            total: 0,
            page: 1,
            page_size: 100,
            pages: 0,
          }),
    enabled: !!workspaceId && !!selectedContact,
  });

  const selectedContactPhone = normalizePhoneForComparison(selectedContact?.phone_number);
  const contactConversations = useMemo(
    () =>
      conversationsData?.items?.filter((conversation) => {
        if (conversation.contact_id === selectedContact?.id) return true;
        return (
          !!selectedContactPhone &&
          normalizePhoneForComparison(conversation.contact_phone) === selectedContactPhone
        );
      }) ?? [],
    [conversationsData?.items, selectedContact?.id, selectedContactPhone],
  );
  const contactConversation: Conversation | undefined = contactConversations[0];
  const isImportedConversation = contactConversation?.source_provider != null;
  // Meta only allows a reply for 24h after the person's last message, and the
  // 7-day human-agent tag does not cover bot replies. Past the deadline every
  // send is rejected, so say so rather than let an operator type into a box that
  // silently fails.
  const messengerWindowClosed = useDeadlinePassed(contactConversation?.messenger_window_expires_at);
  const {
    data: timelineData,
    isLoading: isLoadingTimeline,
    isError: isTimelineError,
    refetch: refetchTimeline,
  } = useContactTimeline(workspaceId ?? "", selectedContact?.id ?? 0, 100);
  const timeline = useMemo(() => timelineData ?? [], [timelineData]);
  const isConversationPending = isConversationsPending;
  const activeFromNumber = selectedFromNumber ?? fallbackFromNumber;

  // Mutations for AI toggle, agent assignment, and clear history
  const toggleAIMutation = useToggleConversationAI(workspaceId ?? "");
  const assignAgentMutation = useAssignAgent(workspaceId ?? "");
  const clearHistoryMutation = useClearConversationHistory(workspaceId ?? "");
  const markReadMutation = useMarkConversationRead(workspaceId ?? "");

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    if (scrollAreaRef.current) {
      const scrollContainer = scrollAreaRef.current.querySelector(
        "[data-radix-scroll-area-viewport]",
      );
      if (scrollContainer) {
        scrollContainer.scrollTop = scrollContainer.scrollHeight;
      }
    }
  }, [timeline]);

  // Group timeline items by date
  type TimelineGroup = { date: Date; items: typeof timeline };
  const groupedTimeline = useMemo(() => {
    const groups: TimelineGroup[] = [];

    timeline.forEach((item) => {
      const itemDate = new Date(item.timestamp);
      const lastGroup = groups[groups.length - 1];

      if (lastGroup && isSameDay(lastGroup.date, itemDate)) {
        lastGroup.items.push(item);
      } else {
        groups.push({ date: itemDate, items: [item] });
      }
    });

    return groups;
  }, [timeline]);

  const previousInboundFor = (sourceItem: TimelineItem): TimelineItem | undefined => {
    const sourceIndex = timeline.findIndex((item) => item.id === sourceItem.id);
    if (sourceIndex <= 0) return undefined;
    return timeline
      .slice(0, sourceIndex)
      .reverse()
      .find((item) => item.direction === "inbound" && item.type === "sms");
  };

  const handleTeachAI = (item: TimelineItem) => {
    if (item.source_provider != null) return;
    if (!item.agent_id) {
      toast.error("This AI reply has no assigned agent to teach");
      return;
    }
    if (!previousInboundFor(item)) {
      toast.error("This AI reply has no prior customer message to learn from");
      return;
    }
    setTeachAIMessage(item);
  };

  const handleSendMessage = async (imageDataUrl?: string) => {
    if (
      isConversationPending ||
      isImportedConversation ||
      (!message.trim() && !imageDataUrl) ||
      !selectedContact ||
      !workspaceId ||
      isSending
    ) {
      return;
    }

    const messageBody = message.trim();
    setMessage("");
    setIsSending(true);

    try {
      await conversationsApi.sendMessageToContact(
        workspaceId,
        selectedContact.id,
        messageBody,
        activeFromNumber,
        imageDataUrl,
      );
      void queryClient.invalidateQueries({
        queryKey: queryKeys.contacts.timeline(workspaceId, selectedContact.id),
      });
      toast.success(imageDataUrl ? "Image sent" : "Message sent");
    } catch (error) {
      setMessage(messageBody);
      toast.error(getApiErrorMessage(error, "Failed to send message"));
      throw error;
    } finally {
      setIsSending(false);
    }
  };

  const handleMessageChange = (value: string) => {
    setMessage(value);
  };

  const handleToggleAI = () => {
    if (isImportedConversation) return;
    if (!contactConversation) {
      toast.error("No conversation found for this contact");
      return;
    }

    const newState = !contactConversation.ai_enabled;
    toggleAIMutation.mutate(
      { conversationId: contactConversation.id, enabled: newState },
      {
        onSuccess: () => {
          toast.success(newState ? "AI engagement enabled" : "AI engagement disabled");
        },
        onError: (err: unknown) => {
          toast.error(getApiErrorMessage(err, "Failed to toggle AI"));
        },
      },
    );
  };

  const handleAssignAgent = (agentId: string | null) => {
    if (isImportedConversation) return;
    if (!contactConversation) {
      toast.error("No conversation found for this contact");
      return;
    }

    assignAgentMutation.mutate(
      { conversationId: contactConversation.id, agentId },
      {
        onSuccess: () => {
          void queryClient.invalidateQueries({
            queryKey: queryKeys.conversations.byContact(workspaceId ?? "", selectedContact?.id),
          });
          toast.success(agentId ? "Agent assigned" : "Agent unassigned");
        },
        onError: (err: unknown) => {
          toast.error(getApiErrorMessage(err, "Failed to assign agent"));
        },
      },
    );
  };

  const handleMarkRead = () => {
    if (!contactConversation) {
      toast.error("No conversation found for this contact");
      return;
    }

    markReadMutation.mutate(contactConversation.id, {
      onSuccess: () => {
        toast.success("Marked as read");
      },
      onError: (err: unknown) => {
        toast.error(getApiErrorMessage(err, "Failed to mark as read"));
      },
    });
  };

  const handleClearHistory = () => {
    if (isImportedConversation) return;
    if (!contactConversation) {
      toast.error("No conversation found for this contact");
      return;
    }

    clearHistoryMutation.mutate(contactConversation.id, {
      onSuccess: () => {
        void queryClient.invalidateQueries({
          queryKey: queryKeys.contacts.timeline(workspaceId ?? "", selectedContact?.id),
        });
        toast.success("Conversation history cleared");
      },
      onError: (err: unknown) => {
        toast.error(getApiErrorMessage(err, "Failed to clear history"));
      },
    });
  };

  const contactName = selectedContact
    ? [selectedContact.first_name, selectedContact.last_name].filter(Boolean).join(" ")
    : undefined;

  if (!selectedContact) {
    return (
      <PageEmptyState
        className={cn("h-full", className)}
        icon={<MessageSquare className="h-8 w-8" />}
        title="Select a contact"
        description="Choose a contact to view their conversation history"
      />
    );
  }

  return (
    <div className={cn("flex flex-col h-full overflow-hidden", className)}>
      <ChatHeader
        workspaceId={workspaceId ?? ""}
        contactId={selectedContact.id}
        contactName={contactName}
        phoneNumber={selectedContact.phone_number}
        conversation={contactConversation}
        agents={agents}
        hasTimelineItems={timeline.length > 0}
        isToggleAIPending={toggleAIMutation.isPending}
        isAssignAgentPending={assignAgentMutation.isPending}
        isClearHistoryPending={clearHistoryMutation.isPending}
        isMarkReadPending={markReadMutation.isPending}
        onToggleAI={handleToggleAI}
        onAssignAgent={handleAssignAgent}
        onClearHistory={handleClearHistory}
        onMarkRead={handleMarkRead}
      />

      {/* Messages */}
      <ScrollArea ref={scrollAreaRef} className="flex-1 min-h-0">
        {isLoadingTimeline ? (
          <LoadingSkeleton />
        ) : isTimelineError ? (
          <PageErrorState
            className="h-full"
            message="We couldn't load this conversation. Please try again."
            onRetry={() => refetchTimeline()}
          />
        ) : timeline.length === 0 ? (
          <PageEmptyState
            className="h-full"
            icon={<MessageSquare className="h-8 w-8" />}
            title="No conversation yet"
            description={
              isImportedConversation
                ? "No messages are available in this imported conversation."
                : "Start a conversation by sending a message, making a call, or scheduling an appointment."
            }
          />
        ) : (
          <div className="py-4">
            <AnimatePresence mode="popLayout">
              {groupedTimeline.map((group) => (
                <div key={group.date.toISOString()}>
                  <DateSeparator date={group.date} />
                  {group.items.map((item) => (
                    <MessageItem
                      key={item.id}
                      item={item}
                      contactName={contactName}
                      onTeachAI={
                        item.source_provider == null && item.agent_id ? handleTeachAI : undefined
                      }
                    />
                  ))}
                </div>
              ))}
            </AnimatePresence>
          </div>
        )}
      </ScrollArea>

      {workspaceId && contactConversation && !isImportedConversation && teachAIMessage && (
        <TeachAIDialog
          open={true}
          onOpenChange={(open) => {
            if (!open) setTeachAIMessage(null);
          }}
          workspaceId={workspaceId}
          conversationId={contactConversation.id}
          sourceMessageId={teachAIMessage.original_id || teachAIMessage.id}
          customerMessage={previousInboundFor(teachAIMessage)?.content ?? ""}
          aiResponse={teachAIMessage.content}
          onSaved={(agentName) => {
            void queryClient.invalidateQueries({
              queryKey: queryKeys.contacts.timeline(workspaceId, selectedContact.id),
            });
            void queryClient.invalidateQueries({
              queryKey: queryKeys.conversations.byContact(workspaceId, selectedContact.id),
            });
            toast.success(`Lesson saved for ${agentName}`);
          }}
        />
      )}

      {isConversationPending ? (
        <div
          role="status"
          className="shrink-0 border-t px-4 py-3 text-center text-xs text-muted-foreground"
        >
          Loading reply controls…
        </div>
      ) : !isImportedConversation && messengerWindowClosed ? (
        <div
          role="status"
          className="shrink-0 border-t px-4 py-3 text-center text-xs text-muted-foreground"
        >
          Reply window closed.{" "}
          {CHANNEL_LABELS[contactConversation?.channel ?? ""] ?? "This channel"} only allows replies
          for 24 hours after their last message — they need to message again before you can respond
          here.
        </div>
      ) : contactConversation && !isImportedConversation ? (
        <MessageComposer
          key={selectedContact.id}
          message={message}
          onMessageChange={handleMessageChange}
          onSend={handleSendMessage}
          isSending={isSending}
          phoneNumbers={phoneNumbers}
          selectedFromNumber={activeFromNumber}
          onFromNumberChange={setSelectedFromNumber}
        />
      ) : null}
    </div>
  );
}
