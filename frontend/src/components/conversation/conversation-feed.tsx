"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { MessageSquare } from "lucide-react";
import { AnimatePresence } from "motion/react";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { PageEmptyState } from "@/components/ui/page-state";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { useWorkspaceId } from "@/hooks/use-workspace-id";
import { useAgents } from "@/hooks/useAgents";
import { useContactTimeline } from "@/hooks/useContacts";
import {
  useToggleConversationAI,
  useAssignAgent,
  useClearConversationHistory,
} from "@/hooks/useConversations";
import { usePhoneNumbers } from "@/hooks/usePhoneNumbers";
import { conversationsApi } from "@/lib/api/conversations";
import { useContactStore } from "@/lib/contact-store";
import { queryKeys } from "@/lib/query-keys";
import { cn } from "@/lib/utils";
import { isSameDay } from "@/lib/utils/date";
import { getApiErrorMessage } from "@/lib/utils/errors";
import type { Conversation } from "@/types";

import { ChatHeader } from "./chat-header";
import { DateSeparator } from "./date-separator";
import { MessageComposer } from "./message-composer";
import { MessageItem } from "./message-item";

interface ConversationFeedProps {
  className?: string;
}

function LoadingSkeleton() {
  return (
    <div className="space-y-4 p-4">
      {Array.from({ length: 5 }).map((_, i) => (
        <div
          key={i}
          className={cn(
            "flex gap-3",
            i % 2 === 0 ? "flex-row" : "flex-row-reverse",
          )}
        >
          <Skeleton className="h-8 w-8 rounded-full shrink-0" />
          <Skeleton
            className={cn("h-16 rounded-2xl", i % 2 === 0 ? "w-48" : "w-64")}
          />
        </div>
      ))}
    </div>
  );
}

export function ConversationFeed({ className }: ConversationFeedProps) {
  const { selectedContact } = useContactStore();
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();

  // Fetch timeline via React Query (polls every 3s)
  const { data: timelineData, isPending: isLoadingTimeline } = useContactTimeline(
    workspaceId ?? "",
    selectedContact?.id ?? 0,
  );
  const timeline = useMemo(() => timelineData ?? [], [timelineData]);
  const [message, setMessage] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [selectedFromNumber, setSelectedFromNumber] = useState<
    string | undefined
  >();
  const scrollAreaRef = useRef<HTMLDivElement>(null);

  // Fetch phone numbers for the workspace
  const { data: phoneNumbersData } = usePhoneNumbers(workspaceId ?? "", {
    sms_enabled: true,
    active_only: true,
  });
  const phoneNumbers = useMemo(
    () => phoneNumbersData?.items ?? [],
    [phoneNumbersData?.items],
  );

  // Fetch agents for the workspace
  const { data: agentsData } = useAgents(workspaceId ?? "");
  const agents = useMemo(
    () => agentsData?.items ?? [],
    [agentsData?.items],
  );

  // Fetch conversations to find the one for the current contact
  const { data: conversationsData } = useQuery({
    queryKey: queryKeys.conversations.byContact(
      workspaceId ?? "",
      selectedContact?.id,
    ),
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

  // Find the conversation for the current contact
  const contactConversation: Conversation | undefined =
    conversationsData?.items?.find(
      (conv) => conv.contact_id === selectedContact?.id,
    );

  // Mutations for AI toggle, agent assignment, and clear history
  const toggleAIMutation = useToggleConversationAI(workspaceId ?? "");
  const assignAgentMutation = useAssignAgent(workspaceId ?? "");
  const clearHistoryMutation = useClearConversationHistory(workspaceId ?? "");

  // Auto-select first phone number when available
  useEffect(() => {
    if (phoneNumbers.length > 0 && !selectedFromNumber) {
      setSelectedFromNumber(phoneNumbers[0].phone_number);
    }
  }, [phoneNumbers, selectedFromNumber]);

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

  const handleSendMessage = async () => {
    if (!message.trim() || !selectedContact || !workspaceId || isSending) return;

    const messageBody = message.trim();
    setMessage("");
    setIsSending(true);

    try {
      await conversationsApi.sendMessageToContact(
        workspaceId,
        selectedContact.id,
        messageBody,
        selectedFromNumber,
      );

      // Invalidate timeline so the sent message appears immediately
      void queryClient.invalidateQueries({
        queryKey: queryKeys.contacts.timelineLegacy(
          workspaceId ?? "",
          selectedContact.id,
        ),
      });
      toast.success("Message sent");
    } catch (error) {
      // Restore the message if sending failed
      setMessage(messageBody);
      const errorMessage =
        error instanceof Error ? error.message : "Failed to send message";
      toast.error(errorMessage);
    } finally {
      setIsSending(false);
    }
  };

  const handleToggleAI = () => {
    if (!contactConversation) {
      toast.error("No conversation found for this contact");
      return;
    }

    const newState = !contactConversation.ai_enabled;
    toggleAIMutation.mutate(
      { conversationId: contactConversation.id, enabled: newState },
      {
        onSuccess: () => {
          toast.success(
            newState ? "AI engagement enabled" : "AI engagement disabled",
          );
        },
        onError: (err: unknown) => {
          toast.error(getApiErrorMessage(err, "Failed to toggle AI"));
        },
      },
    );
  };

  const handleAssignAgent = (agentId: string | null) => {
    if (!contactConversation) {
      toast.error("No conversation found for this contact");
      return;
    }

    assignAgentMutation.mutate(
      { conversationId: contactConversation.id, agentId },
      {
        onSuccess: () => {
          toast.success(agentId ? "Agent assigned" : "Agent unassigned");
        },
        onError: (err: unknown) => {
          toast.error(getApiErrorMessage(err, "Failed to assign agent"));
        },
      },
    );
  };

  const handleClearHistory = () => {
    if (!contactConversation) {
      toast.error("No conversation found for this contact");
      return;
    }

    clearHistoryMutation.mutate(contactConversation.id, {
      onSuccess: () => {
        void queryClient.invalidateQueries({
          queryKey: queryKeys.contacts.timelineLegacy(
            workspaceId ?? "",
            selectedContact?.id,
          ),
        });
        toast.success("Conversation history cleared");
      },
      onError: (err: unknown) => {
        toast.error(getApiErrorMessage(err, "Failed to clear history"));
      },
    });
  };

  const contactName = selectedContact
    ? [selectedContact.first_name, selectedContact.last_name]
        .filter(Boolean)
        .join(" ")
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
        contactName={contactName}
        phoneNumber={selectedContact.phone_number}
        conversation={contactConversation}
        agents={agents}
        hasTimelineItems={timeline.length > 0}
        isToggleAIPending={toggleAIMutation.isPending}
        isAssignAgentPending={assignAgentMutation.isPending}
        isClearHistoryPending={clearHistoryMutation.isPending}
        onToggleAI={handleToggleAI}
        onAssignAgent={handleAssignAgent}
        onClearHistory={handleClearHistory}
      />

      {/* Messages */}
      <ScrollArea ref={scrollAreaRef} className="flex-1 min-h-0">
        {isLoadingTimeline ? (
          <LoadingSkeleton />
        ) : timeline.length === 0 ? (
          <PageEmptyState
            className="h-full"
            icon={<MessageSquare className="h-8 w-8" />}
            title="No conversation yet"
            description="Start a conversation by sending a message, making a call, or scheduling an appointment."
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
                    />
                  ))}
                </div>
              ))}
            </AnimatePresence>
          </div>
        )}
      </ScrollArea>

      <MessageComposer
        message={message}
        onMessageChange={setMessage}
        onSend={handleSendMessage}
        isSending={isSending}
        phoneNumbers={phoneNumbers}
        selectedFromNumber={selectedFromNumber}
        onFromNumberChange={setSelectedFromNumber}
      />
    </div>
  );
}
