"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Play, Sparkles, UserRound } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { RehearsalChat } from "@/components/agents/rehearsal-chat";
import { RehearsalReport } from "@/components/agents/rehearsal-report";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import {
  PageEmptyState,
  PageErrorState,
  PageLoadingState,
} from "@/components/ui/page-state";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { agentsApi } from "@/lib/api/agents";
import { roleplayApi } from "@/lib/api/roleplay";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";
import type { RehearsalRun, RehearseeType } from "@/types/roleplay";

const difficultyVariant: Record<string, "secondary" | "default" | "destructive"> =
  {
    easy: "secondary",
    medium: "default",
    hard: "destructive",
  };

export function PracticeArena({
  initialAgentId = "",
}: {
  initialAgentId?: string;
} = {}) {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();

  const [agentId, setAgentId] = useState<string>(initialAgentId);
  const [personaId, setPersonaId] = useState<string>("");
  const [mode, setMode] = useState<RehearseeType>("ai");
  const [maxTurns, setMaxTurns] = useState<number>(6);
  const [activeRun, setActiveRun] = useState<RehearsalRun | null>(null);

  const {
    data: agentsData,
    isPending: agentsPending,
    error: agentsError,
  } = useQuery({
    queryKey: queryKeys.agents.all(workspaceId ?? ""),
    queryFn: () => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      return agentsApi.list(workspaceId, { active_only: false });
    },
    enabled: !!workspaceId,
  });

  const {
    data: personas,
    isPending: personasPending,
    error: personasError,
  } = useQuery({
    queryKey: queryKeys.roleplay.personas(workspaceId ?? ""),
    queryFn: () => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      return roleplayApi.listPersonas(workspaceId);
    },
    enabled: !!workspaceId,
  });

  const agents = agentsData?.items ?? [];
  const selectedPersona = useMemo(
    () => personas?.find((p) => p.id === personaId) ?? null,
    [personas, personaId],
  );

  const runMutation = useMutation({
    mutationFn: () => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      return roleplayApi.createRun(workspaceId, {
        agent_id: agentId,
        persona_id: personaId,
        rehearsee: mode,
        max_turns: maxTurns,
      });
    },
    onSuccess: (run) => {
      setActiveRun(run);
      if (workspaceId) {
        queryClient.invalidateQueries({
          queryKey: queryKeys.roleplay.runs(workspaceId),
        });
      }
      if (run.status === "failed") {
        toast.error("Rehearsal failed — check the report for details");
      } else if (mode === "ai") {
        toast.success("Rehearsal complete");
      }
    },
    onError: (err: unknown) => {
      toast.error(getApiErrorMessage(err, "Failed to start rehearsal"));
    },
  });

  if (!workspaceId) {
    return <PageLoadingState message="Loading workspace…" />;
  }

  if (agentsPending || personasPending) {
    return <PageLoadingState message="Loading practice arena…" />;
  }

  if (agentsError || personasError) {
    return <PageErrorState message="Failed to load the practice arena." />;
  }

  const canRun = !!agentId && !!personaId && !runMutation.isPending;
  const showReport =
    activeRun &&
    (activeRun.status === "completed" || activeRun.status === "failed");
  const showChat =
    activeRun && activeRun.rehearsee === "human" && activeRun.status === "running";

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-semibold">
          <Sparkles className="size-6 text-primary" />
          Practice Arena
        </h1>
        <p className="text-sm text-muted-foreground">
          Rehearse an agent (or yourself) against synthetic prospects and get a
          scored report before talking to real leads.
        </p>
      </div>

      {agents.length === 0 ? (
        <PageEmptyState
          title="No agents yet"
          description="Create an agent first, then come back to rehearse it."
        />
      ) : (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Set up a rehearsal</CardTitle>
            <CardDescription>
              Pick an agent, choose a prospect persona, and run a simulated
              conversation.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label>Agent</Label>
                <Select value={agentId} onValueChange={setAgentId}>
                  <SelectTrigger>
                    <SelectValue placeholder="Select an agent" />
                  </SelectTrigger>
                  <SelectContent>
                    {agents.map((agent) => (
                      <SelectItem key={agent.id} value={agent.id}>
                        {agent.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label>Prospect persona</Label>
                <Select value={personaId} onValueChange={setPersonaId}>
                  <SelectTrigger>
                    <SelectValue placeholder="Select a persona" />
                  </SelectTrigger>
                  <SelectContent>
                    {(personas ?? []).map((persona) => (
                      <SelectItem key={persona.id} value={persona.id}>
                        {persona.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            {selectedPersona ? (
              <div className="rounded-md border bg-muted/40 p-3 text-sm">
                <div className="mb-1 flex items-center gap-2">
                  <span className="font-medium">{selectedPersona.name}</span>
                  <Badge
                    variant={
                      difficultyVariant[selectedPersona.difficulty] ?? "default"
                    }
                  >
                    {selectedPersona.difficulty}
                  </Badge>
                  {selectedPersona.is_builtin ? (
                    <Badge variant="secondary">built-in</Badge>
                  ) : null}
                </div>
                {selectedPersona.description ? (
                  <p className="text-muted-foreground">
                    {selectedPersona.description}
                  </p>
                ) : null}
                {selectedPersona.objections.length > 0 ? (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {selectedPersona.objections.map((o, i) => (
                      <Badge key={i} variant="outline" className="font-normal">
                        {o}
                      </Badge>
                    ))}
                  </div>
                ) : null}
              </div>
            ) : null}

            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label>Who is practicing?</Label>
                <div className="flex gap-2">
                  <Button
                    type="button"
                    variant={mode === "ai" ? "default" : "outline"}
                    onClick={() => setMode("ai")}
                    className="flex-1"
                  >
                    <Sparkles className="size-4" />
                    AI agent
                  </Button>
                  <Button
                    type="button"
                    variant={mode === "human" ? "default" : "outline"}
                    onClick={() => setMode("human")}
                    className="flex-1"
                  >
                    <UserRound className="size-4" />
                    Me (human rep)
                  </Button>
                </div>
              </div>

              {mode === "ai" ? (
                <div className="space-y-2">
                  <Label>Conversation length</Label>
                  <Select
                    value={String(maxTurns)}
                    onValueChange={(v) => setMaxTurns(Number(v))}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="4">Short (4 turns)</SelectItem>
                      <SelectItem value="6">Standard (6 turns)</SelectItem>
                      <SelectItem value="8">Long (8 turns)</SelectItem>
                      <SelectItem value="10">Thorough (10 turns)</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              ) : null}
            </div>

            <Button
              disabled={!canRun}
              onClick={() => {
                setActiveRun(null);
                runMutation.mutate();
              }}
            >
              {runMutation.isPending ? (
                <>
                  <Loader2 className="size-4 animate-spin" />
                  {mode === "ai" ? "Running rehearsal…" : "Starting…"}
                </>
              ) : (
                <>
                  <Play className="size-4" />
                  {mode === "ai" ? "Run rehearsal" : "Start practice"}
                </>
              )}
            </Button>
            {mode === "ai" && runMutation.isPending ? (
              <p className="text-xs text-muted-foreground">
                Simulating the full conversation and scoring it — this can take a
                moment.
              </p>
            ) : null}
          </CardContent>
        </Card>
      )}

      {showChat && activeRun ? (
        <RehearsalChat
          workspaceId={workspaceId}
          run={activeRun}
          onUpdate={setActiveRun}
          onScored={setActiveRun}
        />
      ) : null}

      {showReport && activeRun ? <RehearsalReport run={activeRun} /> : null}
    </div>
  );
}
