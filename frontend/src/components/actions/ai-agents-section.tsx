"use client";

import { Bot, Sparkles } from "lucide-react";
import { motion, AnimatePresence } from "motion/react";
import { useMemo } from "react";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { useWorkspaceId } from "@/hooks/use-workspace-id";
import { useAgents } from "@/hooks/useAgents";
import { useContactStore } from "@/lib/contact-store";
import { cn } from "@/lib/utils";
import type { Agent } from "@/types";

const channelIcons: Record<string, string> = {
  voice: "Voice",
  text: "Text",
  both: "Voice & Text",
};

interface AgentCardProps {
  agent: Agent;
  isAssigned: boolean;
  isActive: boolean;
  onAssign: () => void;
  onToggle: () => void;
}

function AgentCard({ agent, isAssigned, isActive, onAssign, onToggle }: AgentCardProps) {
  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className={cn(
        "relative p-3 rounded-lg border transition-all",
        isAssigned ? "border-primary bg-primary/5" : "hover:border-muted-foreground/30"
      )}
    >
      <div className="flex items-start gap-3">
        <Avatar className="h-10 w-10 shrink-0">
          <AvatarFallback className={cn(
            "text-sm font-medium",
            agent.is_active ? "bg-primary/10 text-primary" : "bg-muted text-muted-foreground"
          )}>
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
          <p className="text-xs text-muted-foreground line-clamp-2 mt-0.5">
            {agent.description}
          </p>
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
              />
              <span className="text-xs text-muted-foreground">
                {isActive ? "Active" : "Paused"}
              </span>
            </div>
            <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={onAssign}>
              Change
            </Button>
          </>
        ) : (
          <Button
            size="sm"
            variant="outline"
            className="w-full h-7 text-xs"
            onClick={onAssign}
            disabled={!agent.is_active}
          >
            {agent.is_active ? "Assign Agent" : "Agent Inactive"}
          </Button>
        )}
      </div>
    </motion.div>
  );
}

export function AIAgentsSection() {
  const { selectedContact, contactAgents, assignAgent, toggleContactAgent } = useContactStore();
  const workspaceId = useWorkspaceId();
  const { data: agentsData } = useAgents(workspaceId ?? "");
  const agents = useMemo(() => agentsData?.items ?? [], [agentsData?.items]);

  // Find the current assignment for this contact
  const currentAssignment = useMemo(() => {
    if (!selectedContact) return null;
    return contactAgents.find((ca) => ca.contact_id === selectedContact.id);
  }, [selectedContact, contactAgents]);

  const assignedAgent = useMemo(() => {
    if (!currentAssignment) return null;
    return agents.find((a) => a.id === currentAssignment.agent_id);
  }, [agents, currentAssignment]);

  const handleAssign = (agentId: string) => {
    if (!selectedContact) return;
    assignAgent(selectedContact.id, agentId);
  };

  const handleToggle = () => {
    if (!selectedContact) return;
    toggleContactAgent(selectedContact.id);
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
      {assignedAgent && currentAssignment && (
        <div className="mb-2">
          <p className="text-xs font-medium text-muted-foreground mb-2">Currently Assigned</p>
          <AgentCard
            agent={assignedAgent}
            isAssigned={true}
            isActive={currentAssignment.is_active}
            onAssign={() => {}}
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
                  onAssign={() => handleAssign(agent.id)}
                  onToggle={() => {}}
                />
              ))}
          </div>
        </AnimatePresence>
      </div>
    </div>
  );
}
