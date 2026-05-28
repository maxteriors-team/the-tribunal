"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AxiosError } from "axios";
import { Bot, ExternalLink, Loader2, LogOut, ShieldCheck } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { integrationsApi } from "@/lib/api/integrations";
import { queryKeys } from "@/lib/query-keys";
import { useWorkspace } from "@/providers/workspace-provider";

function formatDate(value?: number | string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function getErrorMessage(error: Error, fallback: string): string {
  const axiosError = error as AxiosError<{ detail?: string }>;
  return axiosError.response?.data?.detail || error.message || fallback;
}

export function OpenAIChatGPTCard() {
  const { currentWorkspaceId: workspaceId } = useWorkspace();
  const queryClient = useQueryClient();
  const pollTimer = useRef<number | null>(null);
  const pendingPopup = useRef<Window | null>(null);
  const [isWaitingForCallback, setIsWaitingForCallback] = useState(false);

  const statusQuery = useQuery({
    queryKey: queryKeys.integrations.openAIOAuth(workspaceId ?? ""),
    queryFn: () => integrationsApi.getOpenAIOAuthStatus(workspaceId!),
    enabled: !!workspaceId,
  });

  const invalidateOpenAIQueries = async () => {
    if (!workspaceId) return;
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: queryKeys.integrations.openAIOAuth(workspaceId),
      }),
      queryClient.invalidateQueries({
        queryKey: queryKeys.settings.integrations(workspaceId),
      }),
      queryClient.invalidateQueries({
        queryKey: queryKeys.integrations.bare(workspaceId),
      }),
    ]);
  };

  const pollForConnectedStatus = (attempt = 0) => {
    if (!workspaceId) return;
    if (pollTimer.current) {
      window.clearTimeout(pollTimer.current);
    }

    pollTimer.current = window.setTimeout(async () => {
      const next = await integrationsApi.getOpenAIOAuthStatus(workspaceId);
      queryClient.setQueryData(queryKeys.integrations.openAIOAuth(workspaceId), next);
      if (next.connected) {
        setIsWaitingForCallback(false);
        await invalidateOpenAIQueries();
        toast.success("OpenAI ChatGPT subscription connected");
        return;
      }
      if (attempt < 59) {
        pollForConnectedStatus(attempt + 1);
        return;
      }
      setIsWaitingForCallback(false);
      toast.info("Still waiting for OpenAI sign-in. Click refresh after the success tab appears.");
    }, 2000);
  };

  const startMutation = useMutation({
    mutationFn: () => integrationsApi.startOpenAIOAuth(workspaceId!),
    onSuccess: (result) => {
      if (pendingPopup.current) {
        pendingPopup.current.location.href = result.authorization_url;
      } else {
        window.open(result.authorization_url, "_blank", "noopener,noreferrer");
      }
      pendingPopup.current = null;
      setIsWaitingForCallback(true);
      pollForConnectedStatus();
      toast.success("OpenAI sign-in opened in your browser");
    },
    onError: (error: Error) => {
      pendingPopup.current?.close();
      pendingPopup.current = null;
      setIsWaitingForCallback(false);
      toast.error(getErrorMessage(error, "Failed to start OpenAI sign-in"));
    },
  });

  const disconnectMutation = useMutation({
    mutationFn: () => integrationsApi.disconnectOpenAIOAuth(workspaceId!),
    onSuccess: async () => {
      await invalidateOpenAIQueries();
      toast.success("OpenAI ChatGPT subscription disconnected");
    },
    onError: (error: Error) => {
      toast.error(getErrorMessage(error, "Failed to disconnect OpenAI"));
    },
  });

  useEffect(() => {
    return () => {
      if (pollTimer.current) {
        clearTimeout(pollTimer.current);
      }
    };
  }, []);

  const status = statusQuery.data;
  const connectedStatus = status?.connected ? status : null;
  const isConnected = connectedStatus !== null;

  const handleStart = () => {
    if (!workspaceId) {
      toast.error("No workspace selected. Please select a workspace first.");
      return;
    }
    pendingPopup.current = window.open("about:blank", "openai-codex-oauth");
    startMutation.mutate();
  };

  const handleRefresh = async () => {
    await invalidateOpenAIQueries();
    await statusQuery.refetch();
  };

  const handleDisconnect = () => {
    if (!workspaceId || disconnectMutation.isPending) return;
    if (!window.confirm("Disconnect this workspace from your ChatGPT subscription?")) return;
    disconnectMutation.mutate();
  };

  return (
    <Card className="border-primary/20 bg-primary/5">
      <CardHeader>
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <div className="flex size-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <Bot className="size-5" />
            </div>
            <div>
              <CardTitle className="text-base">ChatGPT subscription for OpenAI Realtime</CardTitle>
              <CardDescription>
                Connect through the OpenAI Codex login flow so voice agents can use {" "}
                <code className="rounded bg-background px-1 font-mono text-xs">
                  {status?.realtime_model ?? "gpt-realtime-2"}
                </code>{" "}
                without a Platform API key.
              </CardDescription>
            </div>
          </div>
          {statusQuery.isPending ? (
            <Badge variant="outline" className="gap-1">
              <Loader2 className="size-3 animate-spin" /> Checking
            </Badge>
          ) : isWaitingForCallback ? (
            <Badge variant="outline" className="gap-1">
              <Loader2 className="size-3 animate-spin" /> Waiting for sign-in
            </Badge>
          ) : isConnected ? (
            <Badge className="border-success/20 bg-success/10 text-success">
              Connected
            </Badge>
          ) : (
            <Badge variant="outline">Not Connected</Badge>
          )}
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        <p className="text-sm text-muted-foreground">
          Click connect, sign in with OpenAI/ChatGPT in the browser, then return here. After the
          callback completes, this workspace will use the subscription OAuth token first and fall
          back to an API key only if no subscription login is connected.
        </p>

        {isConnected && (
          <div className="grid gap-3 rounded-lg border bg-background/70 p-3 text-sm sm:grid-cols-3">
            <div>
              <p className="text-xs font-medium uppercase text-muted-foreground">Account</p>
              <p className="mt-1 break-all font-mono text-xs">
                {connectedStatus?.email || connectedStatus?.account_id || "Connected"}
              </p>
            </div>
            <div>
              <p className="text-xs font-medium uppercase text-muted-foreground">Token expires</p>
              <p className="mt-1">{formatDate(connectedStatus?.expires_at)}</p>
              <p className="text-xs text-muted-foreground">Refreshes automatically.</p>
            </div>
            <div>
              <p className="text-xs font-medium uppercase text-muted-foreground">Signed in</p>
              <p className="mt-1">{formatDate(connectedStatus?.saved_at)}</p>
              {connectedStatus?.plan_type && (
                <p className="text-xs text-muted-foreground">Plan: {connectedStatus.plan_type}</p>
              )}
            </div>
          </div>
        )}

        <div className="flex items-start gap-2 rounded-lg border bg-background/70 p-3 text-xs text-muted-foreground">
          <ShieldCheck className="mt-0.5 size-4 shrink-0 text-primary" />
          <p>
            OAuth tokens are encrypted in the workspace integration store and are never shown in
            the browser. If your browser opens but this card still says not connected, click
            refresh after the OpenAI success tab appears.
          </p>
        </div>
      </CardContent>

      <CardFooter className="flex flex-wrap gap-2">
        {isConnected ? (
          <>
            <Button variant="outline" size="sm" onClick={handleRefresh} disabled={statusQuery.isFetching}>
              {statusQuery.isFetching ? <Loader2 className="size-4 animate-spin" /> : null}
              Refresh status
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={handleDisconnect}
              disabled={disconnectMutation.isPending}
            >
              {disconnectMutation.isPending ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <LogOut className="size-4" />
              )}
              Disconnect
            </Button>
          </>
        ) : (
          <Button
            size="sm"
            onClick={handleStart}
            disabled={startMutation.isPending || isWaitingForCallback || !workspaceId}
          >
            {startMutation.isPending || isWaitingForCallback ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <ExternalLink className="size-4" />
            )}
            {startMutation.isPending
              ? "Preparing sign-in…"
              : isWaitingForCallback
                ? "Waiting for sign-in…"
                : "Connect OpenAI"}
          </Button>
        )}
      </CardFooter>
    </Card>
  );
}
