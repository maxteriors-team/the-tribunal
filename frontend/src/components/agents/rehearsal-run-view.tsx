"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { isRehearsalExecuting, roleplayApi } from "@/lib/api/roleplay";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";
import type { RehearsalRun } from "@/types/roleplay";

import { RehearsalChat } from "./rehearsal-chat";
import { RehearsalReport, rehearsalStatusLabel } from "./rehearsal-report";

export function RehearsalRunView({ workspaceId, runId }: { workspaceId: string; runId: string }) {
  const queryClient = useQueryClient();
  const queryKey = queryKeys.roleplay.run(workspaceId, runId);
  // Do not let URL input become a path segment or a different API resource.
  const validId = /^[a-zA-Z0-9-]{1,128}$/.test(runId);
  const detail = useQuery({
    queryKey,
    queryFn: () => roleplayApi.getRun(workspaceId, runId),
    enabled: validId,
    staleTime: 0,
    refetchOnMount: "always",
    refetchOnWindowFocus: true,
    refetchInterval: (query) =>
      query.state.data && isRehearsalExecuting(query.state.data) ? 2000 : false,
    retry: false,
    throwOnError: false,
  });
  const run = detail.data;
  const updateRun = async (updated: RehearsalRun) => {
    await queryClient.cancelQueries({ queryKey });
    queryClient.setQueryData(queryKey, updated);
    void queryClient.invalidateQueries({ queryKey: queryKeys.roleplay.all(workspaceId) });
  };
  const refreshRun = async () => (await detail.refetch()).data;
  const retry = useMutation({
    mutationFn: () => {
      if (!run?.retryable || run.status !== "failed") throw new Error("This run cannot be retried");
      return roleplayApi.retryRun(workspaceId, runId, run.attempt_count ?? 0);
    },
    onMutate: () => queryClient.cancelQueries({ queryKey }),
    onSuccess: updateRun,
    onError: () => {
      void detail.refetch();
    },
  });

  if (!validId)
    return <p role="alert">This rehearsal link is invalid. Select a saved run from history.</p>;

  return (
    <section aria-label="Selected rehearsal" className="min-w-0 space-y-6">
      <Card>
        <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 space-y-1">
            <CardTitle className="text-base" role="status">
              {!run
                ? detail.isError
                  ? "Rehearsal unavailable"
                  : "Loading rehearsal…"
                : run.status === "failed"
                  ? "Rehearsal failed — unscored"
                  : isRehearsalExecuting(run)
                    ? run.pending_action === "score"
                      ? "Scoring rehearsal…"
                      : "Rehearsal in progress…"
                    : rehearsalStatusLabel(run)}
            </CardTitle>
            <CardDescription>
              {run
                ? `${rehearsalStatusLabel(run)}. Progress is saved; you can leave and reopen this link.`
                : "Loading the saved run does not start a new rehearsal."}
            </CardDescription>
          </div>
          <Button
            variant="outline"
            disabled={detail.isFetching}
            onClick={() => void detail.refetch()}
          >
            Refresh status
          </Button>
        </CardHeader>
        {detail.isError || run?.error || retry.isError || run?.retryable ? (
          <CardContent className="space-y-3">
            {detail.isError ? (
              <p role="alert" className="text-sm text-muted-foreground">
                Couldn&apos;t load the latest saved run. It may be unavailable in this workspace.
                {run
                  ? " Showing the last saved transcript; actions are paused until status refreshes."
                  : " Select a run from history or refresh status."}{" "}
                No rehearsal was restarted.
              </p>
            ) : null}
            {run?.error ? (
              <p className="break-words text-sm text-muted-foreground">{run.error}</p>
            ) : null}
            {retry.isError ? (
              <p role="alert" className="text-sm text-muted-foreground">
                {getApiErrorMessage(retry.error, "Couldn't confirm the retry.")} Refresh status
                before retrying; the same saved run is used.
              </p>
            ) : null}
            {run?.status === "failed" && run.retryable ? (
              <div className="space-y-2">
                <p className="text-sm text-muted-foreground">
                  Retries only the failed step on this run. Provider usage may be charged.
                </p>
                <Button
                  disabled={retry.isPending || detail.isError || detail.isFetching}
                  onClick={() => retry.mutate()}
                >
                  Retry failed step
                </Button>
              </div>
            ) : null}
          </CardContent>
        ) : null}
      </Card>
      {run ? (
        run.rehearsee === "human" && (run.status === "pending" || run.status === "running") ? (
          <RehearsalChat
            workspaceId={workspaceId}
            run={run}
            onUpdate={updateRun}
            onScored={updateRun}
            onRefresh={refreshRun}
            readOnly={detail.isError || detail.isFetching}
          />
        ) : (
          <RehearsalReport run={run} />
        )
      ) : null}
    </section>
  );
}
