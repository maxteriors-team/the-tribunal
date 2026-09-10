"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Play, Sparkles, UserRound } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { RehearsalHistory } from "@/components/agents/rehearsal-history";
import { RehearsalRunView } from "@/components/agents/rehearsal-run-view";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { PageEmptyState, PageErrorState, PageLoadingState } from "@/components/ui/page-state";
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
import { STATIC } from "@/lib/query-options";
import { getApiErrorMessage } from "@/lib/utils/errors";
import type { RehearseeType } from "@/types/roleplay";

const difficultyVariant: Record<string, "secondary" | "default" | "destructive"> = {
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
  if (!workspaceId) return <PageLoadingState message="Loading workspace…" />;
  // Reset drafts and mutation observers at the tenant boundary.
  return (
    <WorkspacePracticeArena
      key={workspaceId}
      workspaceId={workspaceId}
      initialAgentId={initialAgentId}
    />
  );
}

function WorkspacePracticeArena({
  workspaceId,
  initialAgentId,
}: {
  workspaceId: string;
  initialAgentId: string;
}) {
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const urlWorkspace = searchParams.get("workspace");
  const workspaceChanged = !!urlWorkspace && urlWorkspace !== workspaceId;
  const activeRunId = workspaceChanged ? null : searchParams.get("runId");
  const [agentId, setAgentId] = useState(workspaceChanged ? "" : initialAgentId);
  const [personaId, setPersonaId] = useState("");
  const [mode, setMode] = useState<RehearseeType>("ai");
  const [maxTurns, setMaxTurns] = useState(6);

  function runHref(runId?: string) {
    const params = new URLSearchParams(searchParams.toString());
    params.set("workspace", workspaceId);
    if (workspaceChanged) params.delete("agentId");
    if (runId) params.set("runId", runId);
    else params.delete("runId");
    return `/agents/practice?${params.toString()}`;
  }

  useEffect(() => {
    // Bind old deep links too. Switching clears selection before any detail GET.
    if (workspaceChanged || (activeRunId && !urlWorkspace)) {
      const params = new URLSearchParams(window.location.search);
      params.set("workspace", workspaceId);
      if (workspaceChanged) {
        params.delete("runId");
        params.delete("agentId");
      }
      window.history.replaceState(null, "", `/agents/practice?${params.toString()}`);
    }
  }, [workspaceId, workspaceChanged, activeRunId, urlWorkspace]);

  const {
    data: agentsData,
    isPending: agentsPending,
    error: agentsError,
    refetch: refetchAgents,
  } = useQuery({
    queryKey: queryKeys.agents.all(workspaceId),
    queryFn: () => agentsApi.list(workspaceId, { active_only: false }),
    enabled: !activeRunId,
    ...STATIC,
    ...(activeRunId ? { throwOnError: false } : {}),
  });

  const {
    data: personas,
    isPending: personasPending,
    error: personasError,
    refetch: refetchPersonas,
  } = useQuery({
    queryKey: queryKeys.roleplay.personas(workspaceId),
    queryFn: () => roleplayApi.listPersonas(workspaceId),
    enabled: !activeRunId,
    ...STATIC,
    ...(activeRunId ? { throwOnError: false } : {}),
  });

  const agents = agentsData?.items ?? [];
  const selectedPersona = useMemo(
    () => personas?.find((p) => p.id === personaId) ?? null,
    [personas, personaId],
  );

  const runMutation = useMutation({
    mutationFn: () => {
      return roleplayApi.createRun(workspaceId, {
        agent_id: agentId,
        persona_id: personaId,
        rehearsee: mode,
        max_turns: maxTurns,
      });
    },
    onSuccess: (run) => {
      queryClient.setQueryData(queryKeys.roleplay.run(workspaceId, run.id), run);
      void queryClient.invalidateQueries({
        queryKey: queryKeys.roleplay.runs(workspaceId, { limit: 200 }),
      });
    },
    onError: (err: unknown) => {
      toast.error(getApiErrorMessage(err, "Failed to confirm rehearsal creation"));
      void queryClient.invalidateQueries({
        queryKey: queryKeys.roleplay.runs(workspaceId, { limit: 200 }),
      });
    },
  });

  if (!activeRunId && (agentsPending || personasPending)) {
    return <PageLoadingState message="Loading practice arena…" />;
  }

  const retryLoading = () => {
    if (agentsError) void refetchAgents();
    if (personasError) void refetchPersonas();
  };

  if (!activeRunId && ((agentsError && !agentsData) || (personasError && !personas))) {
    return <PageErrorState message="Failed to load the practice arena." onRetry={retryLoading} />;
  }

  const canRun =
    agents.some((agent) => agent.id === agentId) && !!selectedPersona && !runMutation.isPending;

  return (
    <section aria-labelledby="practice-arena-heading" className="min-w-0 space-y-6 p-4 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1
            id="practice-arena-heading"
            className="flex items-center gap-2 text-2xl font-semibold"
          >
            <Sparkles className="size-6 text-primary" />
            Practice Arena
          </h1>
          <p className="text-sm text-muted-foreground">
            Text-only practice with AI prospects. No audio, calls, or messages are sent.
          </p>
        </div>
        {activeRunId ? (
          <Button variant="outline" asChild>
            <Link href={runHref()} scroll={false}>
              New rehearsal
            </Link>
          </Button>
        ) : null}
      </div>

      {!activeRunId && (agentsError || personasError) ? (
        <PageErrorState
          role="alert"
          className="min-h-0 rounded-md border"
          message="Some practice data couldn't refresh. Your selections are unchanged."
          onRetry={retryLoading}
        />
      ) : null}

      {activeRunId ? (
        <RehearsalRunView key={activeRunId} workspaceId={workspaceId} runId={activeRunId} />
      ) : agents.length === 0 ? (
        <PageEmptyState
          title="No agents yet"
          description="Create an agent first, then come back to rehearse it."
        />
      ) : (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Set up a rehearsal</CardTitle>
            <CardDescription>
              Pick an agent and a prospect persona. Scores assess dialogue, not speech or audio
              quality.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="practice-agent">Agent</Label>
                <Select value={agentId} onValueChange={setAgentId}>
                  <SelectTrigger id="practice-agent">
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
                <Label htmlFor="practice-persona">Prospect persona</Label>
                <Select value={personaId} onValueChange={setPersonaId}>
                  <SelectTrigger id="practice-persona">
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
                  <Badge variant={difficultyVariant[selectedPersona.difficulty] ?? "default"}>
                    {selectedPersona.difficulty}
                  </Badge>
                  {selectedPersona.is_builtin ? <Badge variant="secondary">built-in</Badge> : null}
                </div>
                {selectedPersona.description ? (
                  <p className="text-muted-foreground">{selectedPersona.description}</p>
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
                    aria-pressed={mode === "ai"}
                    className="flex-1"
                  >
                    <Sparkles className="size-4" />
                    AI agent
                  </Button>
                  <Button
                    type="button"
                    variant={mode === "human" ? "default" : "outline"}
                    onClick={() => setMode("human")}
                    aria-pressed={mode === "human"}
                    className="flex-1"
                  >
                    <UserRound className="size-4" />
                    Me (human rep)
                  </Button>
                </div>
              </div>

              {mode === "ai" ? (
                <div className="space-y-2">
                  <Label htmlFor="practice-length">Conversation length</Label>
                  <Select value={String(maxTurns)} onValueChange={(v) => setMaxTurns(Number(v))}>
                    <SelectTrigger id="practice-length">
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

            {runMutation.isError ? (
              <p role="alert" className="text-sm text-muted-foreground">
                Couldn&apos;t confirm the request. Check history below for the saved run. Submitting
                the same choices again reuses the original request.
              </p>
            ) : null}
            <Button
              disabled={!canRun}
              onClick={() => {
                const origin = window.location.href;
                runMutation.mutate(undefined, {
                  // Observer callbacks do not navigate after unmount. Also respect
                  // a history selection made while the creation response was pending.
                  onSuccess: (run) => {
                    if (window.location.href === origin) {
                      window.history.pushState(null, "", runHref(run.id));
                    }
                  },
                });
              }}
            >
              {runMutation.isPending ? (
                <>
                  <Loader2 className="size-4 animate-spin" />
                  Saving rehearsal…
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
                Saving your rehearsal. Long conversations continue in the background.
              </p>
            ) : null}
          </CardContent>
        </Card>
      )}

      <RehearsalHistory workspaceId={workspaceId} selectedRunId={activeRunId} runHref={runHref} />
    </section>
  );
}
