"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  Plus,
  MoreHorizontal,
  Play,
  Pause,
  Settings2,
  Trash2,
  Bot,
  Phone,
  PhoneCall,
  MessageSquare,
  Mic,
  Sparkles,
  Loader2,
  Copy,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { PageEmptyState } from "@/components/ui/page-state";
import { PhoneInput } from "@/components/landing/phone-input";
import {
  ResourceListHeader,
  ResourceListStats,
  ResourceListSearch,
  ResourceListLoading,
  ResourceListError,
  ResourceListLayout,
} from "@/components/resource-list";
import { useWorkspaceId } from "@/hooks/use-workspace-id";
import { agentsApi } from "@/lib/api/agents";
import { callsApi } from "@/lib/api/calls";
import { phoneNumbersApi } from "@/lib/api/phone-numbers";
import type { Agent } from "@/types";
import { getApiErrorMessage } from "@/lib/utils/errors";

const channelModeIcons: Record<string, LucideIcon> = {
  voice: Phone,
  text: MessageSquare,
  both: Sparkles,
};

export function AgentsList() {
  const [searchQuery, setSearchQuery] = useState("");
  const [testCallDialogOpen, setTestCallDialogOpen] = useState(false);
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null);
  const [toNumber, setToNumber] = useState("");
  const [fromNumberId, setFromNumberId] = useState("");
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();

  const {
    data: agentsData,
    isPending,
    error,
  } = useQuery({
    queryKey: ["agents", workspaceId],
    queryFn: () => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      return agentsApi.list(workspaceId, { active_only: false });
    },
    enabled: !!workspaceId,
  });

  const toggleAgentMutation = useMutation({
    mutationFn: ({ agentId, isActive }: { agentId: string; isActive: boolean }) => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      return agentsApi.update(workspaceId, agentId, { is_active: isActive });
    },
    onSuccess: () => {
      if (workspaceId) {
        queryClient.invalidateQueries({ queryKey: ["agents", workspaceId] });
      }
      toast.success("Agent status updated");
    },
    onError: (err: unknown) => {
      toast.error(getApiErrorMessage(err, "Failed to update agent status"));
    },
  });

  const deleteAgentMutation = useMutation({
    mutationFn: (agentId: string) => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      return agentsApi.delete(workspaceId, agentId);
    },
    onSuccess: () => {
      if (workspaceId) {
        queryClient.invalidateQueries({ queryKey: ["agents", workspaceId] });
      }
      toast.success("Agent deleted");
    },
    onError: (err: unknown) => {
      toast.error(getApiErrorMessage(err, "Failed to delete agent"));
    },
  });

  const duplicateAgentMutation = useMutation({
    mutationFn: (agent: (typeof agents)[0]) => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      return agentsApi.create(workspaceId, {
        name: `${agent.name} (Copy)`,
        description: agent.description ?? undefined,
        channel_mode: agent.channel_mode,
        voice_provider: agent.voice_provider,
        voice_id: agent.voice_id,
        language: agent.language,
        system_prompt: agent.system_prompt,
        temperature: agent.temperature,
        text_response_delay_ms: agent.text_response_delay_ms,
        text_max_context_messages: agent.text_max_context_messages,
        calcom_event_type_id: agent.calcom_event_type_id ?? undefined,
        enabled_tools: agent.enabled_tools,
        tool_settings: agent.tool_settings,
      });
    },
    onSuccess: () => {
      if (workspaceId) {
        queryClient.invalidateQueries({ queryKey: ["agents", workspaceId] });
      }
      toast.success("Agent duplicated");
    },
    onError: (err: unknown) => {
      toast.error(getApiErrorMessage(err, "Failed to duplicate agent"));
    },
  });

  const { data: phoneNumbersData } = useQuery({
    queryKey: ["phoneNumbers", workspaceId],
    queryFn: () => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      return phoneNumbersApi.list(workspaceId, { voice_enabled: true });
    },
    enabled: !!workspaceId && testCallDialogOpen,
  });

  const initiateCallMutation = useMutation({
    mutationFn: ({ toNumber, fromNumber, agentId }: { toNumber: string; fromNumber: string; agentId: string }) => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      return callsApi.initiate(workspaceId, {
        to_number: toNumber,
        from_phone_number: fromNumber,
        agent_id: agentId,
      });
    },
    onSuccess: () => {
      toast.success("Call initiated successfully");
      setTestCallDialogOpen(false);
      setToNumber("");
      setFromNumberId("");
      setSelectedAgent(null);
    },
    onError: (err: unknown) => {
      toast.error(getApiErrorMessage(err, "Failed to initiate call"));
    },
  });

  const phoneNumbers = phoneNumbersData?.items ?? [];

  const handleTestCall = () => {
    if (!selectedAgent || !toNumber || !fromNumberId) return;
    const fromPhone = phoneNumbers.find((p) => p.id === fromNumberId);
    if (!fromPhone) return;
    initiateCallMutation.mutate({
      toNumber,
      fromNumber: fromPhone.phone_number,
      agentId: selectedAgent.id,
    });
  };

  const openTestCallDialog = (agent: Agent) => {
    setSelectedAgent(agent);
    setTestCallDialogOpen(true);
  };

  const agents = agentsData?.items ?? [];

  const filteredAgents = agents.filter(
    (agent) =>
      agent.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      agent.description?.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const activeAgents = agents.filter((a) => a.is_active).length;

  if (isPending) return <ResourceListLoading />;

  if (error) {
    return (
      <ResourceListError
        resourceName="agents"
        onRetry={() => {
          if (workspaceId) {
            queryClient.invalidateQueries({ queryKey: ["agents", workspaceId] });
          }
        }}
      />
    );
  }

  return (
    <ResourceListLayout
      header={
        <ResourceListHeader
          title="AI Agents"
          subtitle="Configure and manage your AI voice and text agents"
          action={
            <Button asChild>
              <Link href="/agents/create">
                <Plus className="mr-2 size-4" />
                Create Agent
              </Link>
            </Button>
          }
        />
      }
      stats={
        <ResourceListStats
          animated={false}
          columns={3}
          stats={[
            { label: "Total Agents", value: agents.length },
            { label: "Active Agents", value: activeAgents },
            {
              label: "Voice Enabled",
              value: agents.filter(
                (a) => a.channel_mode === "voice" || a.channel_mode === "both"
              ).length,
            },
          ]}
        />
      }
      filterBar={
        <ResourceListSearch
          searchQuery={searchQuery}
          onSearchChange={setSearchQuery}
          placeholder="Search agents..."
          wrapInCard={false}
        />
      }
      isEmpty={filteredAgents.length === 0}
      emptyState={
        <PageEmptyState
          icon={<Bot className="size-12" />}
          title="No agents yet"
          description="Create your first AI agent to start handling calls and messages"
          action={
            <Button asChild>
              <Link href="/agents/create">Create Agent</Link>
            </Button>
          }
        />
      }
      extras={
        <Dialog open={testCallDialogOpen} onOpenChange={setTestCallDialogOpen}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Test Call with {selectedAgent?.name}</DialogTitle>
              <DialogDescription>
                Initiate a test call to verify the AI agent is working correctly.
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-4 py-4">
              <div className="space-y-2">
                <Label htmlFor="to-number">Phone Number to Call</Label>
                <PhoneInput
                  id="to-number"
                  value={toNumber}
                  onChange={setToNumber}
                  placeholder="(555) 123-4567"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="from-number">Call From</Label>
                <Select value={fromNumberId} onValueChange={setFromNumberId}>
                  <SelectTrigger id="from-number" className="w-full">
                    <SelectValue placeholder="Select a phone number" />
                  </SelectTrigger>
                  <SelectContent className="max-h-[300px]">
                    {phoneNumbers.map((phone) => (
                      <SelectItem key={phone.id} value={phone.id}>
                        {phone.phone_number}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {phoneNumbers.length === 0 && (
                  <p className="text-sm text-muted-foreground">
                    No voice-enabled phone numbers available.
                  </p>
                )}
              </div>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setTestCallDialogOpen(false)}>
                Cancel
              </Button>
              <Button
                onClick={handleTestCall}
                disabled={!toNumber || !fromNumberId || initiateCallMutation.isPending}
              >
                {initiateCallMutation.isPending ? (
                  <>
                    <Loader2 className="mr-2 size-4 animate-spin" />
                    Calling...
                  </>
                ) : (
                  <>
                    <PhoneCall className="mr-2 size-4" />
                    Start Call
                  </>
                )}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      }
    >
      <motion.div
        className="grid gap-4 md:grid-cols-2 lg:grid-cols-3"
        initial="hidden"
        animate="visible"
        variants={{
          hidden: { opacity: 0 },
          visible: { opacity: 1, transition: { staggerChildren: 0.07 } },
        }}
      >
        <AnimatePresence mode="popLayout">
          {filteredAgents.map((agent) => {
            const ChannelIcon = channelModeIcons[agent.channel_mode as string] ?? Sparkles;

            return (
              <motion.div
                key={agent.id}
                layout
                variants={{
                  hidden: { opacity: 0, y: 16 },
                  visible: {
                    opacity: 1,
                    y: 0,
                    transition: { type: "spring", stiffness: 300, damping: 24 },
                  },
                }}
                exit={{ opacity: 0, scale: 0.9 }}
              >
                <Card className="group relative overflow-hidden">
                  <div
                    className={`absolute top-0 left-0 right-0 h-1 ${
                      agent.is_active ? "bg-success" : "bg-muted-foreground"
                    }`}
                  />
                  <CardHeader className="pb-3">
                    <div className="flex items-start justify-between">
                      <div className="flex items-center gap-3">
                        <div className="flex size-10 items-center justify-center rounded-full bg-primary/10">
                          <Bot className="size-5 text-primary" />
                        </div>
                        <div>
                          <CardTitle className="text-lg">{agent.name}</CardTitle>
                          <div className="flex items-center gap-2 mt-1">
                            <Badge
                              variant="outline"
                              className="bg-info/10 text-info border-info/20"
                            >
                              {agent.voice_provider}
                            </Badge>
                          </div>
                        </div>
                      </div>
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            className="opacity-0 group-hover:opacity-100"
                          >
                            <MoreHorizontal className="size-4" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          <DropdownMenuItem asChild>
                            <Link href={`/agents/${agent.id}`}>
                              <Settings2 className="mr-2 size-4" />
                              Configure
                            </Link>
                          </DropdownMenuItem>
                          {(agent.channel_mode === "voice" || agent.channel_mode === "both") && (
                            <DropdownMenuItem onClick={() => openTestCallDialog(agent)}>
                              <PhoneCall className="mr-2 size-4" />
                              Test Call
                            </DropdownMenuItem>
                          )}
                          {agent.is_active ? (
                            <DropdownMenuItem
                              onClick={() => toggleAgentMutation.mutate({ agentId: agent.id, isActive: false })}
                            >
                              <Pause className="mr-2 size-4" />
                              Deactivate
                            </DropdownMenuItem>
                          ) : (
                            <DropdownMenuItem
                              onClick={() => toggleAgentMutation.mutate({ agentId: agent.id, isActive: true })}
                            >
                              <Play className="mr-2 size-4" />
                              Activate
                            </DropdownMenuItem>
                          )}
                          <DropdownMenuItem
                            onClick={() => duplicateAgentMutation.mutate(agent)}
                            disabled={duplicateAgentMutation.isPending}
                          >
                            <Copy className="mr-2 size-4" />
                            Duplicate
                          </DropdownMenuItem>
                          <DropdownMenuSeparator />
                          <DropdownMenuItem
                            className="text-destructive"
                            onClick={() => deleteAgentMutation.mutate(agent.id)}
                          >
                            <Trash2 className="mr-2 size-4" />
                            Delete
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </div>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <p className="text-sm text-muted-foreground line-clamp-2">
                      {agent.description ?? "No description"}
                    </p>
                    <div className="flex items-center gap-4 text-sm">
                      <div className="flex items-center gap-1.5">
                        <ChannelIcon className="size-4 text-muted-foreground" />
                        <span className="capitalize">
                          {agent.channel_mode === "both"
                            ? "Voice & Text"
                            : agent.channel_mode}
                        </span>
                      </div>
                      {agent.voice_id && (
                        <div className="flex items-center gap-1.5">
                          <Mic className="size-4 text-muted-foreground" />
                          <span className="capitalize">{agent.voice_id}</span>
                        </div>
                      )}
                    </div>
                  </CardContent>
                  <CardFooter className="border-t pt-4">
                    <div className="flex items-center justify-between w-full">
                      <div className="flex items-center gap-2">
                        <div
                          className={`size-2 rounded-full ${
                            agent.is_active ? "bg-success" : "bg-muted-foreground"
                          }`}
                        />
                        <span className="text-sm text-muted-foreground">
                          {agent.is_active ? "Active" : "Inactive"}
                        </span>
                      </div>
                      <Button variant="outline" size="sm" asChild>
                        <Link href={`/agents/${agent.id}`}>Configure</Link>
                      </Button>
                    </div>
                  </CardFooter>
                </Card>
              </motion.div>
            );
          })}
        </AnimatePresence>
      </motion.div>
    </ResourceListLayout>
  );
}
