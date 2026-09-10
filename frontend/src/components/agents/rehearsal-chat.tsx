"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Send, Trophy } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { isRehearsalExecuting, roleplayApi } from "@/lib/api/roleplay";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";
import type { RehearsalRun } from "@/types/roleplay";

interface RehearsalChatProps {
  workspaceId: string;
  run: RehearsalRun;
  onUpdate: (run: RehearsalRun) => void;
  onScored: (run: RehearsalRun) => void;
  onRefresh?: () => Promise<RehearsalRun | undefined>;
  readOnly?: boolean;
}

export function RehearsalChat({
  workspaceId,
  run,
  onUpdate,
  onScored,
  onRefresh,
  readOnly = false,
}: RehearsalChatProps) {
  const queryClient = useQueryClient();
  const cancelStaleRead = () =>
    queryClient.cancelQueries({ queryKey: queryKeys.roleplay.run(workspaceId, run.id) });
  const [message, setMessage] = useState("");
  const pendingTurn = useRef<{ text: string; version: number } | null>(null);

  const turnMutation = useMutation({
    mutationFn: (text: string) => {
      if (pendingTurn.current?.text !== text) {
        pendingTurn.current = { text, version: run.transcript.length };
      }
      return roleplayApi.advanceTurn(workspaceId, run.id, text, pendingTurn.current.version);
    },
    onMutate: cancelStaleRead,
    onSuccess: (updated) => {
      pendingTurn.current = null;
      setMessage("");
      onUpdate(updated);
    },
    onError: async (err: unknown) => {
      toast.error(getApiErrorMessage(err, "Couldn't confirm the reply. Checking saved status."));
      const latest = await onRefresh?.();
      const pending = pendingTurn.current;
      const saved = pending && latest?.transcript[pending.version];
      if (saved?.role === "agent" && saved.content === pending?.text) {
        pendingTurn.current = null;
        setMessage("");
      }
    },
  });

  const scoreMutation = useMutation({
    mutationFn: () => roleplayApi.scoreRun(workspaceId, run.id),
    onMutate: cancelStaleRead,
    onSuccess: (scored) => {
      onScored(scored);
      if (scored.status === "completed" && scored.overall_score !== null) {
        toast.success("Rehearsal scored");
      } else if (scored.status === "failed") {
        toast.error("Scoring failed — no grade was recorded");
      } else {
        toast.info("Scoring queued. You can return to this rehearsal later.");
      }
    },
    onError: async (err: unknown) => {
      toast.error(getApiErrorMessage(err, "Couldn't confirm scoring. Checking saved status."));
      await onRefresh?.();
    },
  });

  const busy =
    turnMutation.isPending ||
    scoreMutation.isPending ||
    isRehearsalExecuting(run) ||
    run.status !== "running";
  const repTurns = run.transcript.filter((t) => t.role === "agent").length;
  const canReply = !readOnly && !busy && repTurns < run.max_turns;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">
          Practicing against {run.persona_name ?? "the prospect"}
        </CardTitle>
        <p className="text-sm text-muted-foreground">
          Text-only practice. You are the rep. Reply to the prospect, then finish to get scored.
        </p>
      </CardHeader>
      <CardContent className="space-y-4">
        <div role="log" aria-label="Saved dialogue" className="space-y-3 rounded-md border p-3">
          {run.transcript.map((turn, i) => {
            const isProspect = turn.role === "prospect";
            return (
              <div key={i} className={`flex ${isProspect ? "justify-start" : "justify-end"}`}>
                <div
                  className={`max-w-[85%] whitespace-pre-wrap break-words rounded-lg px-3 py-2 text-sm ${
                    isProspect ? "bg-muted" : "bg-primary text-primary-foreground"
                  }`}
                >
                  <div className="mb-1 text-xs opacity-70">
                    {isProspect ? (run.persona_name ?? "Prospect") : "You"}
                  </div>
                  <p>{turn.content}</p>
                </div>
              </div>
            );
          })}
          {busy ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" />
              {run.pending_action === "score" ? "Scoring…" : "Prospect is replying…"}
            </div>
          ) : null}
        </div>

        <div className="flex flex-col gap-2">
          <Textarea
            aria-label="Your reply"
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            placeholder="Type your reply to the prospect…"
            rows={3}
            disabled={!canReply}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && message.trim() && canReply) {
                e.preventDefault();
                turnMutation.mutate(message.trim());
              }
            }}
          />
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-xs text-muted-foreground">
              {repTurns} repl{repTurns === 1 ? "y" : "ies"} sent · ⌘/Ctrl+Enter to send
            </span>
            <div className="flex gap-2">
              <Button
                variant="outline"
                disabled={readOnly || repTurns === 0 || busy}
                onClick={() => scoreMutation.mutate()}
              >
                {scoreMutation.isPending ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <Trophy className="size-4" />
                )}
                Finish &amp; score
              </Button>
              <Button
                disabled={!message.trim() || !canReply}
                onClick={() => turnMutation.mutate(message.trim())}
              >
                <Send className="size-4" />
                Send
              </Button>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
