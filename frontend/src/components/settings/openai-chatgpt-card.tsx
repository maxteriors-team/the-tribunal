"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AxiosError } from "axios";
import { Bot, Clipboard, ExternalLink, Loader2, LogOut, ShieldCheck } from "lucide-react";
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
  const activePollToken = useRef<string | null>(null);
  const [isWaitingForCallback, setIsWaitingForCallback] = useState(false);
  const [deviceLogin, setDeviceLogin] = useState<{
    verificationUrl: string;
    userCode: string;
    expiresAt: number;
  } | null>(null);

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
        queryKey: queryKeys.integrations.all(workspaceId),
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
        activePollToken.current = null;
        setIsWaitingForCallback(false);
        setDeviceLogin(null);
        await invalidateOpenAIQueries();
        toast.success("OpenAI ChatGPT subscription connected");
        return;
      }
      if (attempt < 59) {
        pollForConnectedStatus(attempt + 1);
        return;
      }
      activePollToken.current = null;
      setIsWaitingForCallback(false);
      toast.info("Still waiting for OpenAI sign-in. Click refresh after the success tab appears.");
    }, 2000);
  };

  const pollDeviceCode = (pollToken: string, intervalSeconds: number, attempt = 0) => {
    if (!workspaceId) return;
    if (pollTimer.current) {
      window.clearTimeout(pollTimer.current);
    }

    pollTimer.current = window.setTimeout(async () => {
      try {
        const result = await integrationsApi.pollOpenAIOAuthDeviceCode(workspaceId, pollToken);
        queryClient.setQueryData(
          queryKeys.integrations.openAIOAuth(workspaceId),
          result.status
        );
        if (!result.pending && result.status.connected) {
          activePollToken.current = null;
          setIsWaitingForCallback(false);
          setDeviceLogin(null);
          await invalidateOpenAIQueries();
          toast.success("OpenAI ChatGPT subscription connected");
          return;
        }
        if (attempt < 179 && activePollToken.current === pollToken) {
          pollDeviceCode(pollToken, intervalSeconds, attempt + 1);
          return;
        }
        activePollToken.current = null;
        setIsWaitingForCallback(false);
        toast.info("OpenAI sign-in expired. Start again to get a new device code.");
      } catch (error) {
        activePollToken.current = null;
        setIsWaitingForCallback(false);
        toast.error(getErrorMessage(error as Error, "Failed to check OpenAI sign-in"));
      }
    }, Math.max(intervalSeconds, 1) * 1000);
  };

  const startMutation = useMutation({
    mutationFn: () => integrationsApi.startOpenAIOAuth(workspaceId!),
    onSuccess: (result) => {
      if (result.method === "browser" && result.authorization_url) {
        if (pendingPopup.current) {
          pendingPopup.current.location.href = result.authorization_url;
        } else {
          window.open(result.authorization_url, "_blank", "noopener,noreferrer");
        }
        pendingPopup.current = null;
        setDeviceLogin(null);
        setIsWaitingForCallback(true);
        pollForConnectedStatus();
        toast.success("OpenAI sign-in opened in your browser");
        return;
      }

      if (!result.verification_url || !result.user_code || !result.poll_token) {
        pendingPopup.current?.close();
        pendingPopup.current = null;
        setIsWaitingForCallback(false);
        toast.error("OpenAI did not return complete device-code instructions");
        return;
      }
      if (pendingPopup.current) {
        pendingPopup.current.location.href = result.verification_url;
      } else {
        window.open(result.verification_url, "_blank", "noopener,noreferrer");
      }
      pendingPopup.current = null;
      activePollToken.current = result.poll_token;
      setDeviceLogin({
        verificationUrl: result.verification_url,
        userCode: result.user_code,
        expiresAt: result.expires_at,
      });
      setIsWaitingForCallback(true);
      pollDeviceCode(result.poll_token, result.poll_interval_seconds);
      toast.success("Enter the device code in the OpenAI tab");
    },
    onError: (error: Error) => {
      pendingPopup.current?.close();
      pendingPopup.current = null;
      activePollToken.current = null;
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
    activePollToken.current = null;
    setDeviceLogin(null);
    pendingPopup.current = window.open("about:blank", "openai-codex-oauth");
    pendingPopup.current?.document.write("<p style='font-family: system-ui, sans-serif; padding: 24px;'>Preparing OpenAI sign-in…</p>");
    startMutation.mutate();
  };

  const handleCopyCode = async () => {
    if (!deviceLogin) return;
    await navigator.clipboard.writeText(deviceLogin.userCode);
    toast.success("Device code copied");
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
                Connect through the OpenAI Codex subscription flow so voice agents can use {" "}
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
          Click connect, sign in with OpenAI/ChatGPT, then return here. Hosted deployments use
          OpenAI&apos;s device-code flow, so paste the code shown below into the OpenAI tab. This
          workspace will use the subscription token first and fall back to an API key only if no
          subscription login is connected.
        </p>

        {deviceLogin && !isConnected && (
          <div className="space-y-3 rounded-lg border border-primary/20 bg-background/80 p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="text-sm font-medium">Enter this code in OpenAI</p>
                <p className="text-xs text-muted-foreground">
                  The page opens automatically. If it did not, open {" "}
                  <a
                    href={deviceLogin.verificationUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="text-primary underline-offset-4 hover:underline"
                  >
                    {deviceLogin.verificationUrl}
                  </a>
                  .
                </p>
              </div>
              <Button variant="outline" size="sm" onClick={handleCopyCode}>
                <Clipboard className="size-4" />
                Copy code
              </Button>
            </div>
            <div className="rounded-lg border bg-muted/40 px-4 py-3 text-center font-mono text-2xl font-semibold tracking-[0.35em]">
              {deviceLogin.userCode}
            </div>
            <p className="text-xs text-muted-foreground">
              Expires {formatDate(deviceLogin.expiresAt)}. This card will update automatically after
              OpenAI confirms the sign-in.
            </p>
          </div>
        )}

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
            the browser. If the card still says not connected after OpenAI confirms the sign-in,
            click refresh.
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
