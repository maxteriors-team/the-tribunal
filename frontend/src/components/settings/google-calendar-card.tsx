"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AxiosError } from "axios";
import { CalendarCheck, ExternalLink, Loader2, LogOut, ShieldCheck } from "lucide-react";
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

export function GoogleCalendarCard() {
  const { currentWorkspaceId: workspaceId } = useWorkspace();
  const queryClient = useQueryClient();
  const pollTimer = useRef<number | null>(null);
  const pendingPopup = useRef<Window | null>(null);
  const [isWaitingForCallback, setIsWaitingForCallback] = useState(false);

  const statusQuery = useQuery({
    queryKey: queryKeys.integrations.googleCalendar(workspaceId ?? ""),
    queryFn: () => integrationsApi.getGoogleCalendarStatus(workspaceId!),
    enabled: !!workspaceId,
  });

  const invalidateQueries = async () => {
    if (!workspaceId) return;
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: queryKeys.integrations.googleCalendar(workspaceId),
      }),
      queryClient.invalidateQueries({
        queryKey: queryKeys.integrations.all(workspaceId),
      }),
    ]);
  };

  const pollForConnectedStatus = (attempt = 0) => {
    if (!workspaceId) return;
    if (pollTimer.current) window.clearTimeout(pollTimer.current);

    pollTimer.current = window.setTimeout(async () => {
      const next = await integrationsApi.getGoogleCalendarStatus(workspaceId);
      queryClient.setQueryData(queryKeys.integrations.googleCalendar(workspaceId), next);
      if (next.connected) {
        setIsWaitingForCallback(false);
        await invalidateQueries();
        toast.success("Google Calendar connected");
        return;
      }
      if (attempt < 59) {
        pollForConnectedStatus(attempt + 1);
        return;
      }
      setIsWaitingForCallback(false);
      toast.info("Still waiting for Google sign-in. Click refresh after the success tab appears.");
    }, 2000);
  };

  const connectMutation = useMutation({
    mutationFn: () => integrationsApi.connectGoogleCalendar(workspaceId!),
    onSuccess: (result) => {
      if (pendingPopup.current) {
        pendingPopup.current.location.href = result.authorization_url;
      } else {
        window.open(result.authorization_url, "_blank", "noopener,noreferrer");
      }
      pendingPopup.current = null;
      setIsWaitingForCallback(true);
      pollForConnectedStatus();
      toast.success("Google sign-in opened in your browser");
    },
    onError: (error: Error) => {
      pendingPopup.current?.close();
      pendingPopup.current = null;
      setIsWaitingForCallback(false);
      toast.error(getErrorMessage(error, "Failed to start Google sign-in"));
    },
  });

  const disconnectMutation = useMutation({
    mutationFn: () => integrationsApi.disconnectGoogleCalendar(workspaceId!),
    onSuccess: async () => {
      await invalidateQueries();
      toast.success("Google Calendar disconnected");
    },
    onError: (error: Error) => {
      toast.error(getErrorMessage(error, "Failed to disconnect Google Calendar"));
    },
  });

  useEffect(() => {
    return () => {
      if (pollTimer.current) clearTimeout(pollTimer.current);
    };
  }, []);

  const status = statusQuery.data;
  const isConnected = status?.connected ?? false;
  const clientConfigured = status?.client_configured ?? false;

  const handleConnect = () => {
    if (!workspaceId) {
      toast.error("No workspace selected. Please select a workspace first.");
      return;
    }
    pendingPopup.current = window.open("about:blank", "google-calendar-oauth");
    pendingPopup.current?.document.write(
      "<p style='font-family: system-ui, sans-serif; padding: 24px;'>Preparing Google sign-in…</p>"
    );
    connectMutation.mutate();
  };

  const handleRefresh = async () => {
    await invalidateQueries();
    await statusQuery.refetch();
  };

  const handleDisconnect = () => {
    if (!workspaceId || disconnectMutation.isPending) return;
    if (!window.confirm("Disconnect this workspace from Google Calendar?")) return;
    disconnectMutation.mutate();
  };

  return (
    <Card className="border-primary/20 bg-primary/5">
      <CardHeader>
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <div className="flex size-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <CalendarCheck className="size-5" />
            </div>
            <div>
              <CardTitle className="text-base">Google Calendar</CardTitle>
              <CardDescription>
                Connect this workspace&apos;s Google account so AI agents can read live
                availability and auto-book appointments (with a Google Meet link) directly on
                your calendar.
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
            <Badge className="border-success/20 bg-success/10 text-success">Connected</Badge>
          ) : (
            <Badge variant="outline">Not Connected</Badge>
          )}
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {!clientConfigured && !isConnected && (
          <div className="rounded-lg border border-warning/30 bg-warning/10 p-3 text-xs text-muted-foreground">
            Google Calendar OAuth isn&apos;t configured on this deployment yet. An admin must set
            the Google OAuth client credentials before this workspace can connect.
          </div>
        )}

        <p className="text-sm text-muted-foreground">
          Click connect, choose the Google account that owns the booking calendar, then return
          here. Once connected, availability checks and bookings route to Google Calendar instead
          of Cal.com.
        </p>

        {isConnected && (
          <div className="grid gap-3 rounded-lg border bg-background/70 p-3 text-sm sm:grid-cols-3">
            <div>
              <p className="text-xs font-medium uppercase text-muted-foreground">Calendar</p>
              <p className="mt-1 break-all font-mono text-xs">
                {status?.google_calendar_id || "primary"}
              </p>
            </div>
            <div>
              <p className="text-xs font-medium uppercase text-muted-foreground">Token expires</p>
              <p className="mt-1">{formatDate(status?.token_expiry)}</p>
              <p className="text-xs text-muted-foreground">Refreshes automatically.</p>
            </div>
            <div>
              <p className="text-xs font-medium uppercase text-muted-foreground">Connected</p>
              <p className="mt-1">{formatDate(status?.saved_at)}</p>
            </div>
          </div>
        )}

        <div className="flex items-start gap-2 rounded-lg border bg-background/70 p-3 text-xs text-muted-foreground">
          <ShieldCheck className="mt-0.5 size-4 shrink-0 text-primary" />
          <p>
            OAuth tokens are encrypted at rest and never shown in the browser. If the card still
            says not connected after Google confirms the sign-in, click refresh.
          </p>
        </div>
      </CardContent>

      <CardFooter className="flex flex-wrap gap-2">
        {isConnected ? (
          <>
            <Button
              variant="outline"
              size="sm"
              onClick={handleRefresh}
              disabled={statusQuery.isFetching}
            >
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
            onClick={handleConnect}
            disabled={
              connectMutation.isPending ||
              isWaitingForCallback ||
              !workspaceId ||
              !clientConfigured
            }
          >
            {connectMutation.isPending || isWaitingForCallback ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <ExternalLink className="size-4" />
            )}
            {connectMutation.isPending
              ? "Preparing sign-in…"
              : isWaitingForCallback
                ? "Waiting for sign-in…"
                : "Connect Google Calendar"}
          </Button>
        )}
      </CardFooter>
    </Card>
  );
}
