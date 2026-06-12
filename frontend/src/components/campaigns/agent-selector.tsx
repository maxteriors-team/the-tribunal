"use client";

import { Bot, MessageSquare, Phone, Sparkles, Check, ArrowRight } from "lucide-react";
import { motion } from "motion/react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import type { Agent } from "@/types";

interface AgentSelectorProps {
  agents: Agent[];
  selectedId?: string;
  onSelect: (agentId: string | undefined) => void;
  showTextAgentsOnly?: boolean;
  showVoiceAgentsOnly?: boolean;
  allowNone?: boolean;
}


export function AgentSelector({
  agents,
  selectedId,
  onSelect,
  showTextAgentsOnly = false,
  showVoiceAgentsOnly = false,
  allowNone = true,
}: AgentSelectorProps) {
  // Filter agents based on channel mode requirements
  const filteredAgents = agents.filter((a) => {
    if (showVoiceAgentsOnly) {
      return a.channel_mode === "voice" || a.channel_mode === "both";
    }
    if (showTextAgentsOnly) {
      return a.channel_mode === "text" || a.channel_mode === "both";
    }
    return true;
  });

  const getChannelIcon = (mode: string) => {
    switch (mode) {
      case "voice":
        return <Phone className="size-3" />;
      case "text":
        return <MessageSquare className="size-3" />;
      case "both":
        return (
          <div className="flex gap-0.5">
            <Phone className="size-3" />
            <MessageSquare className="size-3" />
          </div>
        );
      default:
        return null;
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Bot className="size-4" />
        <span>
          Select an AI agent to handle responses ({filteredAgents.length} available)
        </span>
      </div>

      <ScrollArea className="h-[350px]">
        <div className="space-y-2 pr-4">
          {/* No agent option - only show if allowNone is true */}
          {allowNone && (
            <motion.div
              whileHover={{ scale: 1.01 }}
              whileTap={{ scale: 0.99 }}
              onClick={() => onSelect(undefined)}
              className={`relative p-4 rounded-lg border-2 cursor-pointer transition-colors ${
                !selectedId
                  ? "border-primary bg-primary/5"
                  : "border-border hover:border-primary/50"
              }`}
            >
              {!selectedId && (
                <div className="absolute top-3 right-3">
                  <div className="size-5 rounded-full bg-primary flex items-center justify-center">
                    <Check className="size-3 text-primary-foreground" />
                  </div>
                </div>
              )}
              <div className="flex items-center gap-3">
                <div className="size-10 rounded-full bg-muted flex items-center justify-center">
                  <Bot className="size-5 text-muted-foreground" />
                </div>
                <div>
                  <div className="font-medium">No AI Agent</div>
                  <div className="text-sm text-muted-foreground">
                    Manual responses only - no automated replies
                  </div>
                </div>
              </div>
            </motion.div>
          )}

          {/* Agent cards */}
          {filteredAgents.map((agent) => {
            const isSelected = selectedId === agent.id;

            return (
              <motion.div
                key={agent.id}
                whileHover={{ scale: 1.01 }}
                whileTap={{ scale: 0.99 }}
                onClick={() => onSelect(agent.id)}
                className={`relative p-4 rounded-lg border-2 cursor-pointer transition-colors ${
                  isSelected
                    ? "border-primary bg-primary/5"
                    : "border-border hover:border-primary/50"
                }`}
              >
                {isSelected && (
                  <div className="absolute top-3 right-3">
                    <div className="size-5 rounded-full bg-primary flex items-center justify-center">
                      <Check className="size-3 text-primary-foreground" />
                    </div>
                  </div>
                )}

                <div className="flex items-start gap-3">
                  <div className="size-10 rounded-full bg-gradient-to-br from-primary/20 to-primary/5 flex items-center justify-center">
                    <Sparkles className="size-5 text-primary" />
                  </div>

                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-medium">{agent.name}</span>
                      <Badge variant="outline" className="flex items-center gap-1">
                        {getChannelIcon(agent.channel_mode)}
                        <span className="capitalize">{agent.channel_mode}</span>
                      </Badge>
                    </div>

                    {agent.description && (
                      <p className="text-sm text-muted-foreground mt-1 line-clamp-2">
                        {agent.description}
                      </p>
                    )}

                    {agent.system_prompt && (
                      <div className="mt-2 p-2 bg-muted/50 rounded text-xs text-muted-foreground line-clamp-2">
                        <span className="font-medium">Prompt:</span>{" "}
                        {agent.system_prompt}
                      </div>
                    )}
                  </div>
                </div>
              </motion.div>
            );
          })}

          {filteredAgents.length === 0 && (
            <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
              <Bot className="size-12 mb-2 opacity-50" />
              <p>
                {showVoiceAgentsOnly
                  ? "No voice-capable agents found"
                  : showTextAgentsOnly
                  ? "No text-capable agents found"
                  : "No agents found"}
              </p>
              <p className="text-xs mt-1">
                {showVoiceAgentsOnly
                  ? "Create an agent with voice channel support"
                  : showTextAgentsOnly
                  ? "Create an agent with text channel support"
                  : "Create an agent to get started"}
              </p>
              <Button variant="link" asChild className="mt-2 h-auto p-0">
                <Link href="/agents/create">
                  Create an agent
                  <ArrowRight className="size-4" />
                </Link>
              </Button>
            </div>
          )}
        </div>
      </ScrollArea>
    </div>
  );
}
