"use client";

import * as React from "react";
import {
  Phone,
  MoreVertical,
  Loader2,
  Bot,
  User,
  Trash2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
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
import type { Agent } from "@/types/agent";
import type { Conversation } from "@/types";

interface ChatHeaderProps {
  contactName?: string;
  phoneNumber?: string | null;
  conversation?: Conversation;
  agents: Agent[];
  hasTimelineItems: boolean;
  isToggleAIPending: boolean;
  isAssignAgentPending: boolean;
  isClearHistoryPending: boolean;
  onToggleAI: () => void;
  onAssignAgent: (agentId: string | null) => void;
  onClearHistory: () => void;
}

export function ChatHeader({
  contactName,
  phoneNumber,
  conversation,
  agents,
  hasTimelineItems,
  isToggleAIPending,
  isAssignAgentPending,
  isClearHistoryPending,
  onToggleAI,
  onAssignAgent,
  onClearHistory,
}: ChatHeaderProps) {
  const [showClearHistoryDialog, setShowClearHistoryDialog] = React.useState(false);

  const handleConfirmClear = () => {
    onClearHistory();
    setShowClearHistoryDialog(false);
  };

  const assignedAgentName = conversation?.assigned_agent_id
    ? agents.find((a) => a.id === conversation.assigned_agent_id)?.name ?? "Agent"
    : "No Agent";

  return (
    <>
      <div className="flex items-center justify-between px-4 py-3 border-b shrink-0">
        <div className="flex items-center gap-3">
          <h2 className="font-semibold">{contactName}</h2>
          {phoneNumber && (
            <span className="text-sm text-muted-foreground">{phoneNumber}</span>
          )}
        </div>
        <div className="flex items-center gap-1">
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
            <span className="text-xs">
              {conversation?.ai_enabled ? "AI On" : "AI Off"}
            </span>
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
              {agents.map((agent) => (
                <DropdownMenuItem
                  key={agent.id}
                  onClick={() => onAssignAgent(agent.id)}
                  disabled={!conversation || isAssignAgentPending}
                >
                  <Bot className="h-4 w-4 mr-2" />
                  {agent.name}
                </DropdownMenuItem>
              ))}
              {agents.length === 0 && (
                <DropdownMenuItem disabled>
                  <span className="text-muted-foreground text-sm">
                    No agents available
                  </span>
                </DropdownMenuItem>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
          <Button
            size="icon"
            variant="ghost"
            className="h-8 w-8"
            aria-label="Call contact"
          >
            <Phone className="h-4 w-4" />
          </Button>
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
              <DropdownMenuItem>View contact details</DropdownMenuItem>
              <DropdownMenuItem>Schedule appointment</DropdownMenuItem>
              <DropdownMenuItem>Add note</DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                className="text-destructive"
                onClick={() => setShowClearHistoryDialog(true)}
                disabled={!conversation || !hasTimelineItems}
              >
                <Trash2 className="h-4 w-4 mr-2" />
                Clear history
              </DropdownMenuItem>
              <DropdownMenuItem className="text-destructive">
                Archive
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {/* Clear History Confirmation Dialog */}
      <AlertDialog
        open={showClearHistoryDialog}
        onOpenChange={setShowClearHistoryDialog}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Clear conversation history?</AlertDialogTitle>
            <AlertDialogDescription>
              This will permanently delete all messages in this conversation.
              This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleConfirmClear}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              disabled={isClearHistoryPending}
            >
              {isClearHistoryPending ? (
                <Loader2 className="h-4 w-4 animate-spin mr-2" />
              ) : null}
              Clear history
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
