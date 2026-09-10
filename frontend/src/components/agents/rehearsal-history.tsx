"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { isRehearsalExecuting, roleplayApi } from "@/lib/api/roleplay";
import { queryKeys } from "@/lib/query-keys";
import { POLL_15S } from "@/lib/query-options";

import { rehearsalStatusLabel } from "./rehearsal-report";

export function RehearsalHistory({
  workspaceId,
  selectedRunId,
  runHref,
}: {
  workspaceId: string;
  selectedRunId: string | null;
  runHref: (runId: string) => string;
}) {
  // Observe the detail cache without fetching, so the selected row never lags
  // behind the transcript's faster polling or an accepted turn/retry.
  const { data: selectedRun } = useQuery({
    queryKey: queryKeys.roleplay.run(workspaceId, selectedRunId ?? ""),
    queryFn: () => roleplayApi.getRun(workspaceId, selectedRunId!),
    enabled: false,
    throwOnError: false,
  });
  // simplification: the API caps history at 200; older browsing needs server pagination.
  const history = useQuery({
    queryKey: queryKeys.roleplay.runs(workspaceId, { limit: 200 }),
    queryFn: () => roleplayApi.listRuns(workspaceId, { limit: 200 }),
    ...POLL_15S,
    refetchInterval: (query) =>
      query.state.data?.some(isRehearsalExecuting) ? POLL_15S.refetchInterval : false,
    refetchOnMount: "always",
    refetchOnWindowFocus: true,
    retry: false,
    throwOnError: false,
  });

  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <CardTitle className="text-base">Rehearsal history</CardTitle>
          <CardDescription>
            Up to 200 most recent runs in this workspace. Opening a run never restarts it.
          </CardDescription>
        </div>
        <Button
          variant="outline"
          disabled={history.isFetching}
          onClick={() => void history.refetch()}
        >
          {history.isError ? "Retry history" : "Refresh history"}
        </Button>
      </CardHeader>
      <CardContent>
        {history.isError ? (
          <p role="alert" className="mb-3 text-sm text-muted-foreground">
            History couldn&apos;t refresh.{" "}
            {history.data ? "Showing the last saved list." : "Retry to load saved runs."} No
            rehearsal was restarted.
          </p>
        ) : null}
        {history.isPending ? (
          <p role="status" className="text-sm text-muted-foreground">
            Loading history…
          </p>
        ) : null}
        {!history.isError && history.data?.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No rehearsals yet. Your first run will appear here.
          </p>
        ) : null}
        {history.data && history.data.length > 0 ? (
          <ul aria-label="Saved rehearsals" className="divide-y">
            {history.data.map((summary) => {
              const run = summary.id === selectedRun?.id ? selectedRun : summary;
              return (
                <li key={run.id}>
                  <Link
                    href={runHref(run.id)}
                    prefetch={false}
                    scroll={false}
                    aria-current={selectedRunId === run.id ? "page" : undefined}
                    className="flex flex-wrap items-center justify-between gap-2 rounded-md p-3 text-sm transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring aria-[current=page]:bg-muted"
                  >
                    <div className="min-w-0 space-y-1 break-words">
                      <p className="font-medium">
                        {run.agent_name ?? "Unavailable agent"} vs{" "}
                        {run.persona_name ?? "Unavailable persona"}
                      </p>
                      <p className="text-muted-foreground">
                        {run.rehearsee === "human" ? "Human rep" : "AI agent"} · Text-only ·{" "}
                        {run.channel} script
                      </p>
                      <time dateTime={run.created_at} className="text-xs text-muted-foreground">
                        {new Date(run.created_at).toLocaleString()}
                      </time>
                    </div>
                    <span>
                      {rehearsalStatusLabel(run)}
                      {run.status === "completed" && run.overall_score !== null
                        ? ` · ${Math.round(run.overall_score)}/100`
                        : ""}
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
        ) : null}
      </CardContent>
    </Card>
  );
}
