"use client";

import { Phone, MoreVertical, History, Loader2, Bot, Check, User, Trash2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { ClientNoteDialog } from "@/components/contacts/client-note-dialog";
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
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useCapabilities } from "@/hooks/useCapabilities";
import type { Conversation } from "@/types";
import type { Agent } from "@/types/agent";
import { CHANNEL_LABELS } from "@/types/conversation";

interface ChatHeaderProps {
  workspaceId: string;
  contactId: number;
  contactName?: string;
  phoneNumber?: string | null;
  conversation?: Conversation;
  agents: Agent[];
  hasTimelineItems: boolean;
  isToggleAIPending: boolean;
  isAssignAgentPending: boolean;
  isClearHistoryPending: boolean;
  isMarkReadPending: boolean;
  onToggleAI: () => void;
  onAssignAgent: (agentId: string | null) => void;
  onClearHistory: () => void;
  onMarkRead: () => void;
}

export function ChatHeader({
  workspaceId,
  contactId,
  contactName,
  phoneNumber,
  conversation,
  agents,
  hasTimelineItems,
  isToggleAIPending,
  isAssignAgentPending,
  isClearHistoryPending,
  isMarkReadPending,
  onToggleAI,
  onAssignAgent,
  onClearHistory,
  onMarkRead,
}: ChatHeaderProps) {
  const { can } = useCapabilities();
  const [showClientNoteDialog, setShowClientNoteDialog] = useState(false);
  const [showClearHistoryDialog, setShowClearHistoryDialog] = useState(false);

  const handleConfirmClear = () => {
    onClearHistory();
    setShowClearHistoryDialog(false);
  };

  const unreadCount = conversation?.unread_count ?? 0;
  const isImportedConversation = conversation?.source_provider != null;
  // SMS is the default and needs no badge; every other channel gets one, because
  // the reply rules differ per channel.
  const channelLabel = CHANNEL_LABELS[conversation?.channel ?? ""];

  const assignedAgentName = conversation?.assigned_agent_id
    ? (agents.find((a) => a.id === conversation.assigned_agent_id)?.name ?? "Agent")
    : "No Agent";

  return (
    <>
      <div className="flex items-center justify-between gap-2 px-4 py-3 border-b shrink-0">
        <div className="flex min-w-0 items-center gap-3">
          <h2 className="truncate font-semibold">{contactName}</h2>
          {unreadCount > 0 ? (
            <Badge variant="default" className="h-5 shrink-0 px-1.5 text-[10px]">
              {unreadCount} new
            </Badge>
          ) : null}
          {phoneNumber && (
            <span className="hidden truncate text-sm text-muted-foreground sm:inline">
              {phoneNumber}
            </span>
          )}
          {isImportedConversation ? (
            <Badge variant="outline" className="h-5 shrink-0 px-1.5 text-[10px]">
              Imported history
            </Badge>
          ) : null}
          {channelLabel ? (
            <Badge variant="outline" className="h-5 shrink-0 px-1.5 text-[10px]">
              {channelLabel}
            </Badge>
          ) : null}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {!isImportedConversation ? (
            <>
              {/* AI Toggle Button */}
              <Button
                size="sm"
                variant={conversation?.ai_enabled ? "default" : "outline"}
                className="h-8 gap-1.5"
                onClick={onToggleAI}
                disabled={!conversation || isToggleAIPending}
              >
                {isToggleAIPending ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Bot className="h-3.5 w-3.5" />
                )}
                <span className="text-xs">{conversation?.ai_enabled ? "AI On" : "AI Off"}</span>
              </Button>
              {/* Agent Selector */}
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button size="sm" variant="outline" className="h-8 gap-1.5">
                    <User className="h-3.5 w-3.5" />
                    <span className="text-xs max-w-[60vw] sm:max-w-[100px] truncate">
                      {assignedAgentName}
                    </span>
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-48">
                  <DropdownMenuItem
                    onClick={() => onAssignAgent(null)}
                    disabled={!conversation || isAssignAgentPending}
                  >
                    <span className="text-muted-foreground">No Agent</span>
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  {agents.map((agent, index) => (
                    <DropdownMenuItem
                      key={index}
                      onClick={() => onAssignAgent(agent.id)}
                      disabled={!conversation || isAssignAgentPending}
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
            </>
          ) : null}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                size="icon"
                variant="ghost"
                className="h-8 w-8"
                aria-label="Conversation actions"
              >
                <MoreVertical className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem asChild>
                <Link href={`/contacts/${contactId}/details`}>
                  <History className="h-4 w-4 mr-2" />
                  View details &amp; history
                </Link>
              </DropdownMenuItem>
              <DropdownMenuItem>Schedule appointment</DropdownMenuItem>
              {can("crm:write") && (
                <DropdownMenuItem onSelect={() => setShowClientNoteDialog(true)}>
                  Add note
                </DropdownMenuItem>
              )}
              <DropdownMenuItem
                onClick={onMarkRead}
                disabled={unreadCount === 0 || isMarkReadPending}
              >
                {isMarkReadPending ? (
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                ) : (
                  <Check className="h-4 w-4 mr-2" />
                )}
                Mark as read
              </DropdownMenuItem>
              {!isImportedConversation ? (
                <>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    className="text-destructive"
                    onClick={() => setShowClearHistoryDialog(true)}
                    disabled={!conversation || !hasTimelineItems}
                  >
                    <Trash2 className="h-4 w-4 mr-2" />
                    Clear history
                  </DropdownMenuItem>
                  <DropdownMenuItem className="text-destructive">Archive</DropdownMenuItem>
                </>
              ) : null}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {/* Clear History Confirmation Dialog */}
      <AlertDialog open={showClearHistoryDialog} onOpenChange={setShowClearHistoryDialog}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Clear conversation history?</AlertDialogTitle>
            <AlertDialogDescription>
              This will permanently delete all messages in this conversation. This action cannot be
              undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleConfirmClear}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              disabled={isClearHistoryPending}
            >
              {isClearHistoryPending ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
              Clear history
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      <ClientNoteDialog
        workspaceId={workspaceId}
        contactId={contactId}
        contactName={contactName}
        open={showClientNoteDialog}
        onOpenChange={setShowClientNoteDialog}
      />
    </>
  );
}
