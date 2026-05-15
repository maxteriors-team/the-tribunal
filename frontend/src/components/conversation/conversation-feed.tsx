"use client";

import * as React from "react";
import { AnimatePresence } from "motion/react";
import { formatLongDate, isToday, isYesterday, isSameDay } from "@/lib/utils/date";
import { Send, Paperclip, Mic, Phone, MoreVertical, MessageSquare, Loader2, PhoneOutgoing, Bot, User, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { PageEmptyState } from "@/components/ui/page-state";
import { Skeleton } from "@/components/ui/skeleton";
import { Separator } from "@/components/ui/separator";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { usePhoneNumbers } from "@/hooks/usePhoneNumbers";
import { useAgents } from "@/hooks/useAgents";
import { useToggleConversationAI, useAssignAgent, useClearConversationHistory } from "@/hooks/useConversations";
import { useContactStore } from "@/lib/contact-store";
import { useContactTimeline } from "@/hooks/useContacts";
import { useWorkspaceId } from "@/hooks/use-workspace-id";
import { queryKeys } from "@/lib/query-keys";
import { conversationsApi } from "@/lib/api/conversations";
import { MessageItem } from "./message-item";
import type { Conversation } from "@/types";
import { getApiErrorMessage } from "@/lib/utils/errors";

interface ConversationFeedProps {
  className?: string;
}

function formatDateLabel(date: Date): string {
  if (isToday(date)) return "Today";
  if (isYesterday(date)) return "Yesterday";
  return formatLongDate(date);
}

function DateSeparator({ date }: { date: Date }) {
  return (
    <div className="flex items-center gap-4 py-4 px-4">
      <Separator className="flex-1" />
      <span className="text-xs text-muted-foreground font-medium">
        {formatDateLabel(date)}
      </span>
      <Separator className="flex-1" />
    </div>
  );
}

function EmptyState() {
  return (
    <PageEmptyState
      className="h-full"
      icon={<MessageSquare className="h-8 w-8" />}
      title="No conversation yet"
      description="Start a conversation by sending a message, making a call, or scheduling an appointment."
    />
  );
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

export function ConversationFeed({ className }: ConversationFeedProps) {
  const { selectedContact } = useContactStore();
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();

  // Fetch timeline via React Query (polls every 3s)
  const { data: timelineData, isPending: isLoadingTimeline } = useContactTimeline(
    workspaceId ?? "",
    selectedContact?.id ?? 0,
  );
  const timeline = React.useMemo(() => timelineData ?? [], [timelineData]);
  const [message, setMessage] = React.useState("");
  const [isSending, setIsSending] = React.useState(false);
  const [selectedFromNumber, setSelectedFromNumber] = React.useState<string | undefined>();
  const [showClearHistoryDialog, setShowClearHistoryDialog] = React.useState(false);
  const scrollAreaRef = React.useRef<HTMLDivElement>(null);
  const textareaRef = React.useRef<HTMLTextAreaElement>(null);

  // Fetch phone numbers for the workspace
  const { data: phoneNumbersData } = usePhoneNumbers(workspaceId ?? "", { sms_enabled: true, active_only: true });
  const phoneNumbers = React.useMemo(() => phoneNumbersData?.items ?? [], [phoneNumbersData?.items]);

  // Fetch agents for the workspace
  const { data: agentsData } = useAgents(workspaceId ?? "");
  const agents = React.useMemo(() => agentsData?.items ?? [], [agentsData?.items]);

  // Fetch conversations to find the one for the current contact
  const { data: conversationsData } = useQuery({
    queryKey: queryKeys.conversations.byContact(workspaceId ?? "", selectedContact?.id),
    queryFn: () =>
      workspaceId
        ? conversationsApi.list(workspaceId, { page: 1, page_size: 100 })
        : Promise.resolve({ items: [], total: 0, page: 1, page_size: 100, pages: 0 }),
    enabled: !!workspaceId && !!selectedContact,
  });

  // Find the conversation for the current contact
  const contactConversation: Conversation | undefined = conversationsData?.items?.find(
    (conv) => conv.contact_id === selectedContact?.id
  );

  // Mutations for AI toggle, agent assignment, and clear history
  const toggleAIMutation = useToggleConversationAI(workspaceId ?? "");
  const assignAgentMutation = useAssignAgent(workspaceId ?? "");
  const clearHistoryMutation = useClearConversationHistory(workspaceId ?? "");

  // Auto-select first phone number when available
  React.useEffect(() => {
    if (phoneNumbers.length > 0 && !selectedFromNumber) {
      setSelectedFromNumber(phoneNumbers[0].phone_number);
    }
  }, [phoneNumbers, selectedFromNumber]);

  // Auto-scroll to bottom when new messages arrive
  React.useEffect(() => {
    if (scrollAreaRef.current) {
      const scrollContainer = scrollAreaRef.current.querySelector("[data-radix-scroll-area-viewport]");
      if (scrollContainer) {
        scrollContainer.scrollTop = scrollContainer.scrollHeight;
      }
    }
  }, [timeline]);

  // Group timeline items by date
  type TimelineGroup = { date: Date; items: typeof timeline };
  const groupedTimeline = React.useMemo(() => {
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
        selectedFromNumber
      );

      // Invalidate timeline so the sent message appears immediately
      void queryClient.invalidateQueries({
        queryKey: queryKeys.contacts.timelineLegacy(workspaceId ?? "", selectedContact.id),
      });
      toast.success("Message sent");
    } catch (error) {
      // Restore the message if sending failed
      setMessage(messageBody);
      const errorMessage = error instanceof Error ? error.message : "Failed to send message";
      toast.error(errorMessage);
    } finally {
      setIsSending(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
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
          toast.success(newState ? "AI engagement enabled" : "AI engagement disabled");
        },
        onError: (err: unknown) => {
          toast.error(getApiErrorMessage(err, "Failed to toggle AI"));
        },
      }
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
      }
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
          queryKey: queryKeys.contacts.timelineLegacy(workspaceId ?? "", selectedContact?.id),
        });
        toast.success("Conversation history cleared");
        setShowClearHistoryDialog(false);
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
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b shrink-0">
        <div className="flex items-center gap-3">
          <h2 className="font-semibold">{contactName}</h2>
          {selectedContact.phone_number && (
            <span className="text-sm text-muted-foreground">
              {selectedContact.phone_number}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          {/* AI Toggle Button */}
          <Button
            size="sm"
            variant={contactConversation?.ai_enabled ? "default" : "outline"}
            className="h-8 gap-1.5"
            onClick={handleToggleAI}
            disabled={!contactConversation || toggleAIMutation.isPending}
          >
            {toggleAIMutation.isPending ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Bot className="h-3.5 w-3.5" />
            )}
            <span className="text-xs">
              {contactConversation?.ai_enabled ? "AI On" : "AI Off"}
            </span>
          </Button>
          {/* Agent Selector */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button size="sm" variant="outline" className="h-8 gap-1.5">
                <User className="h-3.5 w-3.5" />
                <span className="text-xs max-w-[100px] truncate">
                  {contactConversation?.assigned_agent_id
                    ? agents.find((a) => a.id === contactConversation.assigned_agent_id)?.name ?? "Agent"
                    : "No Agent"}
                </span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-48">
              <DropdownMenuItem
                onClick={() => handleAssignAgent(null)}
                disabled={!contactConversation || assignAgentMutation.isPending}
              >
                <span className="text-muted-foreground">No Agent</span>
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              {agents.map((agent) => (
                <DropdownMenuItem
                  key={agent.id}
                  onClick={() => handleAssignAgent(agent.id)}
                  disabled={!contactConversation || assignAgentMutation.isPending}
                >
                  <Bot className="h-4 w-4 mr-2" />
                  {agent.name}
                </DropdownMenuItem>
              ))}
              {agents.length === 0 && (
                <DropdownMenuItem disabled>
                  <span className="text-muted-foreground text-sm">No agents available</span>
                </DropdownMenuItem>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
          <Button size="icon" variant="ghost" className="h-8 w-8" aria-label="Call contact">
            <Phone className="h-4 w-4" />
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button size="icon" variant="ghost" className="h-8 w-8" aria-label="Conversation actions">
                <MoreVertical className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem>View contact details</DropdownMenuItem>
              <DropdownMenuItem>Schedule appointment</DropdownMenuItem>
              <DropdownMenuItem>Add note</DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                className="text-destructive"
                onClick={() => setShowClearHistoryDialog(true)}
                disabled={!contactConversation || timeline.length === 0}
              >
                <Trash2 className="h-4 w-4 mr-2" />
                Clear history
              </DropdownMenuItem>
              <DropdownMenuItem className="text-destructive">Archive</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {/* Messages */}
      <ScrollArea ref={scrollAreaRef} className="flex-1 min-h-0">
        {isLoadingTimeline ? (
          <LoadingSkeleton />
        ) : timeline.length === 0 ? (
          <EmptyState />
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

      {/* Message Input */}
      <div className="p-4 border-t shrink-0">
        {/* Phone number selector */}
        {phoneNumbers.length > 1 && (
          <div className="flex items-center gap-2 mb-2">
            <PhoneOutgoing className="h-4 w-4 text-muted-foreground" />
            <span className="text-xs text-muted-foreground">Send from:</span>
            <Select value={selectedFromNumber} onValueChange={setSelectedFromNumber}>
              <SelectTrigger size="sm" className="h-7 text-xs">
                <SelectValue placeholder="Select number" />
              </SelectTrigger>
              <SelectContent>
                {phoneNumbers.map((phone) => (
                  <SelectItem key={phone.id} value={phone.phone_number}>
                    {phone.phone_number}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}
        <div className="flex items-end gap-2">
          <Button size="icon" variant="ghost" className="h-9 w-9 shrink-0" disabled={isSending} aria-label="Attach file">
            <Paperclip className="h-4 w-4" />
          </Button>
          <div className="flex-1 relative">
            <Textarea
              ref={textareaRef}
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Type a message..."
              className="min-h-[40px] max-h-[120px] resize-none pr-12"
              rows={1}
              disabled={isSending}
            />
            <Button
              size="icon"
              variant="ghost"
              className="absolute right-1 bottom-1 h-8 w-8"
              disabled={isSending}
              aria-label="Voice message"
            >
              <Mic className="h-4 w-4" />
            </Button>
          </div>
          <Button
            size="icon"
            className="h-9 w-9 shrink-0"
            onClick={handleSendMessage}
            disabled={!message.trim() || isSending}
            aria-label="Send message"
          >
            {isSending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Send className="h-4 w-4" />
            )}
          </Button>
        </div>
      </div>

      {/* Clear History Confirmation Dialog */}
      <AlertDialog open={showClearHistoryDialog} onOpenChange={setShowClearHistoryDialog}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Clear conversation history?</AlertDialogTitle>
            <AlertDialogDescription>
              This will permanently delete all messages in this conversation. This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleClearHistory}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              disabled={clearHistoryMutation.isPending}
            >
              {clearHistoryMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin mr-2" />
              ) : null}
              Clear history
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
