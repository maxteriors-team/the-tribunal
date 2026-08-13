"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Calendar, Loader2 } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useEffect, useRef } from "react";
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
import { googleCalendarApi } from "@/lib/api/google-calendar";

const statusKey = ["google-calendar", "status"] as const;

interface GoogleCalendarCardProps {
  returnPath?: string;
}

export function GoogleCalendarCard({
  returnPath = "/settings?tab=calendar",
}: GoogleCalendarCardProps = {}) {
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const handledResult = useRef<string | null>(null);
  const status = useQuery({
    queryKey: statusKey,
    queryFn: googleCalendarApi.getStatus,
  });

  const connect = useMutation({
    mutationFn: () => googleCalendarApi.authorize(`${window.location.origin}${returnPath}`),
    onSuccess: ({ authorization_url }) => {
      window.location.assign(authorization_url);
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const disconnect = useMutation({
    mutationFn: googleCalendarApi.disconnect,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: statusKey });
      toast.success("Google Calendar disconnected");
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const data = status.data;
  const busy = status.isPending || connect.isPending || disconnect.isPending;

  useEffect(() => {
    const result = searchParams.get("google_calendar");
    if (!result || handledResult.current === result) return;
    handledResult.current = result;
    void queryClient.invalidateQueries({ queryKey: statusKey });
    if (result === "connected") {
      toast.success("Google Calendar connected");
    } else {
      toast.error(searchParams.get("detail") || "Google Calendar connection failed");
    }
  }, [queryClient, searchParams]);

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <Calendar className="size-5" aria-hidden="true" />
            </div>
            <div>
              <CardTitle className="text-base">Google Calendar</CardTitle>
              <CardDescription>
                Your AI checks your availability and books meetings on your calendar.
              </CardDescription>
            </div>
          </div>
          <Badge variant={data?.connected ? "default" : "outline"}>
            {data?.connected ? "Connected" : "Not connected"}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-2 text-sm text-muted-foreground">
        {status.isPending ? (
          <div className="flex items-center gap-2">
            <Loader2 className="size-4 animate-spin" aria-hidden="true" />
            Checking connection…
          </div>
        ) : data?.connected ? (
          <>
            <p>
              Connected as <span className="font-medium text-foreground">{data.google_email}</span>
            </p>
            <p>
              Team routing uses each sales rep&apos;s own connection. Managers and dispatchers can
              still see all appointments on the CRM calendar.
            </p>
          </>
        ) : data?.configured ? (
          <p>
            Connect the Google account where your own appointments should be created. Each sales rep
            connects their account separately.
          </p>
        ) : (
          <p>
            Google OAuth application credentials must be configured by an administrator before team
            members can connect.
          </p>
        )}
      </CardContent>
      <CardFooter>
        {data?.connected ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={busy}
            onClick={() => disconnect.mutate()}
          >
            {disconnect.isPending && (
              <Loader2 className="mr-2 size-4 animate-spin" aria-hidden="true" />
            )}
            Disconnect
          </Button>
        ) : (
          <Button
            type="button"
            size="sm"
            disabled={busy || !data?.configured}
            onClick={() => connect.mutate()}
          >
            {connect.isPending && (
              <Loader2 className="mr-2 size-4 animate-spin" aria-hidden="true" />
            )}
            Connect Google Calendar
          </Button>
        )}
      </CardFooter>
    </Card>
  );
}
