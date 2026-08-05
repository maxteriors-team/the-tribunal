"use client";

import { useQuery } from "@tanstack/react-query";
import { Headphones, Loader2, PhoneCall, PhoneOff, Radio } from "lucide-react";
import { useState } from "react";

import { LiveCallSupervisor } from "@/components/calls/live-call-supervisor";
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
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useHangupCall } from "@/hooks/useHangupCall";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { callsApi, type LiveCall } from "@/lib/api/calls";
import { queryKeys } from "@/lib/query-keys";

function formatDuration(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

/** How a call is named to the operator, in the row and in the confirm prompt. */
function callLabel(call: LiveCall): string {
  return call.contact_name || call.contact_phone || "Unknown contact";
}

/**
 * Live-call roster + supervision entry point.
 *
 * Polls the workspace's in-progress calls and, for each, exposes a "Supervise"
 * action that opens the listen / whisper / barge panel, plus an "End call"
 * action that drops the call from here without waiting for the far end.
 *
 * Ending a call is instant and unrecoverable, and its button sits next to
 * "Supervise" in a polling roster whose rows can reorder underneath the cursor,
 * so it is confirmed first — the same guard the destructive actions on Quotes
 * and Lead Sources use.
 */
export function LiveCallsPanel() {
  const workspaceId = useWorkspaceId();
  const [activeCall, setActiveCall] = useState<LiveCall | null>(null);
  const [callPendingConfirm, setCallPendingConfirm] = useState<LiveCall | null>(null);

  const { data } = useQuery({
    queryKey: queryKeys.calls.live(workspaceId ?? ""),
    queryFn: () => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      return callsApi.listLive(workspaceId);
    },
    enabled: Boolean(workspaceId),
    // Live roster: poll frequently so calls appear/disappear promptly.
    refetchInterval: 5000,
  });

  const hangupCall = useHangupCall({
    workspaceId,
    onSuccess: (callId) => {
      // Dropping the call the supervisor panel is watching leaves it pointed at
      // a dead call, so close it.
      setActiveCall((current) => (current?.call_id === callId ? null : current));
    },
  });

  const liveCalls = data?.items ?? [];

  if (liveCalls.length === 0) {
    return null;
  }

  return (
    <Card className="border-success/40">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <Radio className="h-4 w-4 text-success animate-pulse" />
          Live calls
          <Badge variant="secondary">{liveCalls.length}</Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {liveCalls.map((call) => (
          <div
            key={call.call_id}
            className="flex items-center justify-between gap-3 rounded-md border p-3"
          >
            <div className="flex items-center gap-3 min-w-0">
              <div className="flex-shrink-0 size-9 rounded-full bg-primary/10 flex items-center justify-center">
                <PhoneCall className="size-4 text-primary" />
              </div>
              <div className="min-w-0">
                <div className="truncate text-sm font-medium">{callLabel(call)}</div>
                <div className="truncate text-xs text-muted-foreground">
                  {call.direction}
                  {call.agent_name ? ` · ${call.agent_name}` : ""} ·{" "}
                  {formatDuration(call.duration_seconds)}
                  {call.barged ? " · operator on call" : ""}
                  {call.supervisor_count > 0 ? ` · ${call.supervisor_count} watching` : ""}
                </div>
              </div>
            </div>
            <div className="flex flex-shrink-0 items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                className="gap-2"
                onClick={() => setActiveCall(call)}
              >
                <Headphones className="h-4 w-4" />
                Supervise
              </Button>
              <Button
                variant="destructive"
                size="sm"
                className="gap-2"
                // One hook instance drives the whole roster, so gate on the id
                // being dropped: a bare `isPending` freezes every other row's
                // button too.
                disabled={hangupCall.isPending && hangupCall.variables === call.call_id}
                onClick={() => setCallPendingConfirm(call)}
              >
                {hangupCall.isPending && hangupCall.variables === call.call_id ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <PhoneOff className="h-4 w-4" />
                )}
                End call
              </Button>
            </div>
          </div>
        ))}
      </CardContent>

      <LiveCallSupervisor
        open={activeCall !== null}
        onOpenChange={(open) => {
          if (!open) setActiveCall(null);
        }}
        workspaceId={workspaceId ?? ""}
        call={activeCall}
      />

      <AlertDialog
        open={callPendingConfirm !== null}
        onOpenChange={(open) => {
          if (!open) setCallPendingConfirm(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>End this call?</AlertDialogTitle>
            <AlertDialogDescription>
              {callPendingConfirm
                ? `The call with ${callLabel(callPendingConfirm)} will be hung up immediately. This cannot be undone.`
                : null}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep call</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() =>
                callPendingConfirm && hangupCall.mutate(callPendingConfirm.call_id)
              }
            >
              End call
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  );
}
