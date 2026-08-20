"use client";

import { useQuery } from "@tanstack/react-query";
import { Bot, Sparkles } from "lucide-react";
import { motion, AnimatePresence } from "motion/react";
import { useMemo } from "react";
import { toast } from "sonner";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { useAgents } from "@/hooks/useAgents";
import { useAssignContactAgent, useToggleContactAI } from "@/hooks/useContacts";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { conversationsApi } from "@/lib/api/conversations";
import { useContactStore } from "@/lib/contact-store";
import { queryKeys } from "@/lib/query-keys";
import { cn } from "@/lib/utils";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { normalizePhoneForComparison } from "@/lib/utils/phone";
import type { Agent, Conversation } from "@/types";

const channelIcons: Record<string, string> = {
  voice: "Voice",
  text: "Text",
  both: "Voice & Text",
};

interface AgentCardProps {
  agent: Agent;
  isAssigned: boolean;
  isActive: boolean;
  isPending: boolean;
  onAssign: () => void;
  onUnassign: () => void;
  onToggle: () => void;
}

function AgentCard({
  agent,
  isAssigned,
  isActive,
  isPending,
  onAssign,
  onUnassign,
  onToggle,
}: AgentCardProps) {
  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className={cn(
        "relative p-3 rounded-lg border transition-all",
        isAssigned ? "border-primary bg-primary/5" : "hover:border-muted-foreground/30",
      )}
    >
      <div className="flex items-start gap-3">
        <Avatar className="h-10 w-10 shrink-0">
          <AvatarFallback
            className={cn(
              "text-sm font-medium",
              agent.is_active ? "bg-primary/10 text-primary" : "bg-muted text-muted-foreground",
            )}
          >
            <Bot className="h-5 w-5" />
          </AvatarFallback>
        </Avatar>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-medium text-sm truncate">{agent.name}</span>
            {isAssigned && (
              <Badge variant="secondary" className="text-xs bg-primary/10 text-primary">
                Assigned
              </Badge>
            )}
          </div>
          <p className="text-xs text-muted-foreground line-clamp-2 mt-0.5">{agent.description}</p>
          <div className="flex items-center gap-2 mt-2">
            <span className="text-xs text-muted-foreground">
              {channelIcons[agent.channel_mode]}
            </span>
          </div>
        </div>
      </div>

      {/* Actions */}
      <div className="flex items-center justify-between mt-3 pt-3 border-t">
        {isAssigned ? (
          <>
            <div className="flex items-center gap-2">
              <Switch
                checked={isActive}
                onCheckedChange={onToggle}
                className="data-[state=checked]:bg-primary"
                disabled={isPending}
              />
              <span className="text-xs text-muted-foreground">
                {isActive ? "Active" : "Paused"}
              </span>
            </div>
            <Button
              size="sm"
              variant="ghost"
              className="h-7 text-xs"
              onClick={onUnassign}
              disabled={isPending}
            >
              Unassign
            </Button>
          </>
        ) : (
          <Button
            size="sm"
            variant="outline"
            className="w-full h-7 text-xs"
            onClick={onAssign}
            disabled={!agent.is_active || isPending}
          >
            {agent.is_active ? "Assign Agent" : "Agent Inactive"}
          </Button>
        )}
      </div>
    </motion.div>
  );
}

export function AIAgentsSection() {
  const { selectedContact } = useContactStore();
  const workspaceId = useWorkspaceId();
  const { data: agentsData } = useAgents(workspaceId ?? "");
  const agents = useMemo(() => agentsData?.items ?? [], [agentsData?.items]);
  const assignAgentMutation = useAssignContactAgent(workspaceId ?? "");
  const toggleAIMutation = useToggleContactAI(workspaceId ?? "");

  const { data: conversationsData } = useQuery({
    queryKey: queryKeys.conversations.byContact(workspaceId ?? "", selectedContact?.id),
    queryFn: () =>
      workspaceId
        ? conversationsApi.list(workspaceId, { page: 1, page_size: 100 })
        : Promise.resolve({ items: [], total: 0, page: 1, page_size: 100, pages: 0 }),
    enabled: !!workspaceId && !!selectedContact,
  });

  const selectedContactPhone = normalizePhoneForComparison(selectedContact?.phone_number);

  const contactConversation: Conversation | undefined = conversationsData?.items?.find(
    (conversation) => {
      if (conversation.contact_id === selectedContact?.id) return true;
      return (
        !!selectedContactPhone &&
        normalizePhoneForComparison(conversation.contact_phone) === selectedContactPhone
      );
    },
  );

  const assignedAgentId = contactConversation?.assigned_agent_id;
  const assignedAgent = useMemo(() => {
    if (!assignedAgentId) return null;
    return agents.find((agent) => agent.id === assignedAgentId) ?? null;
  }, [agents, assignedAgentId]);

  const handleAssign = (agentId: string | null) => {
    if (!selectedContact) return;

    assignAgentMutation.mutate(
      { contactId: selectedContact.id, agentId },
      {
        onSuccess: () => {
          toast.success(agentId ? "Agent assigned" : "Agent unassigned");
        },
        onError: (error) => {
          toast.error(getApiErrorMessage(error, "Failed to assign agent"));
        },
      },
    );
  };

  const handleToggle = () => {
    if (!selectedContact || !contactConversation) return;

    const enabled = !contactConversation.ai_enabled;
    toggleAIMutation.mutate(
      { contactId: selectedContact.id, enabled },
      {
        onSuccess: () => {
          toast.success(enabled ? "Agent resumed" : "Agent paused");
        },
        onError: (error) => {
          toast.error(getApiErrorMessage(error, "Failed to update agent status"));
        },
      },
    );
  };

  if (!selectedContact) {
    return (
      <div className="text-center py-8 text-sm text-muted-foreground">
        Select a contact to manage AI agents
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Sparkles className="h-4 w-4 text-primary" />
        <h3 className="text-sm font-semibold">AI Agents</h3>
        <Badge variant="secondary" className="text-xs ml-auto">
          {agents.filter((a) => a.is_active).length} available
        </Badge>
      </div>

      <p className="text-xs text-muted-foreground">
        Assign an AI agent to automatically handle conversations with this contact.
      </p>

      {/* Assigned Agent (if any) */}
      {assignedAgent && contactConversation && (
        <div className="mb-2">
          <p className="text-xs font-medium text-muted-foreground mb-2">Currently Assigned</p>
          <AgentCard
            agent={assignedAgent}
            isAssigned={true}
            isActive={contactConversation.ai_enabled}
            isPending={assignAgentMutation.isPending || toggleAIMutation.isPending}
            onAssign={() => handleAssign(assignedAgent.id)}
            onUnassign={() => handleAssign(null)}
            onToggle={handleToggle}
          />
        </div>
      )}

      {/* Available Agents */}
      <div>
        <p className="text-xs font-medium text-muted-foreground mb-2">
          {assignedAgent ? "Other Agents" : "Available Agents"}
        </p>
        <AnimatePresence mode="popLayout">
          <div className="space-y-2">
            {agents
              .filter((a) => a.id !== assignedAgent?.id)
              .map((agent) => (
                <AgentCard
                  key={agent.id}
                  agent={agent}
                  isAssigned={false}
                  isActive={false}
                  isPending={assignAgentMutation.isPending || toggleAIMutation.isPending}
                  onAssign={() => handleAssign(agent.id)}
                  onUnassign={() => handleAssign(null)}
                  onToggle={() => {}}
                />
              ))}
          </div>
        </AnimatePresence>
      </div>
    </div>
  );
}
