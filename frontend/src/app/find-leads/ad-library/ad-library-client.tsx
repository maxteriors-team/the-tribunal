"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Clock, Loader2 } from "lucide-react";
import { useCallback, useState } from "react";
import { toast } from "sonner";

import { AdvertiserDetail } from "@/components/ad-library/advertiser-detail";
import {
  AdvertiserTable,
  AdvertiserTableToolbar,
} from "@/components/ad-library/advertiser-table";
import { MonitorsPanel } from "@/components/ad-library/monitors";
import {
  AdLibrarySearchForm,
  toSearchRequest,
  type AdLibrarySearchValues,
} from "@/components/ad-library/search-form";
import { Card, CardContent } from "@/components/ui/card";
import {
  PageEmptyState,
  PageErrorState,
  PageLoadingState,
} from "@/components/ui/page-state";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import {
  adLibraryApi,
  adLibraryQueryOptions,
  type AdAdvertiser,
  type AdLibraryJob,
} from "@/lib/api/ad-library";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";

export function AdLibraryClient() {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();
  const [job, setJob] = useState<AdLibraryJob | null>(null);
  const [onlyQualified, setOnlyQualified] = useState(true);
  const [selected, setSelected] = useState<AdAdvertiser | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  const invalidateAdvertisers = useCallback(() => {
    if (workspaceId) {
      queryClient.invalidateQueries({
        queryKey: queryKeys.adLibrary.all(workspaceId),
      });
    }
  }, [queryClient, workspaceId]);

  const toggleSelect = useCallback((advertiserId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(advertiserId)) next.delete(advertiserId);
      else next.add(advertiserId);
      return next;
    });
  }, []);

  const promoteMutation = useMutation({
    mutationFn: (advertiserId: string) => {
      if (!workspaceId) throw new Error("No workspace");
      return adLibraryApi.promoteAdvertiser(workspaceId, advertiserId, {
        create_opportunity: true,
        enroll_in_sequence: false,
      });
    },
    onSuccess: (result) => {
      toast.success(
        result.promoted ? "Added to CRM" : `Skipped: ${result.skipped_reason ?? "unknown"}`,
      );
      invalidateAdvertisers();
    },
    onError: (error) => toast.error(getApiErrorMessage(error, "Couldn't promote advertiser")),
  });

  const bulkPromoteMutation = useMutation({
    mutationFn: () => {
      if (!workspaceId) throw new Error("No workspace");
      return adLibraryApi.bulkPromote(workspaceId, {
        advertiser_ids: Array.from(selectedIds),
        create_opportunity: true,
        enroll_in_sequence: false,
      });
    },
    onSuccess: (result) => {
      toast.success(`Promoted ${result.promoted_count}, skipped ${result.skipped_count}`);
      setSelectedIds(new Set());
      invalidateAdvertisers();
    },
    onError: (error) => toast.error(getApiErrorMessage(error, "Couldn't promote advertisers")),
  });

  const searchMutation = useMutation({
    mutationFn: async (values: AdLibrarySearchValues) => {
      if (!workspaceId) throw new Error("No workspace");
      return adLibraryApi.search(workspaceId, toSearchRequest(values));
    },
    onSuccess: (created) => {
      setJob(created);
      toast.success("Ad library search started");
    },
    onError: (error) => {
      toast.error(getApiErrorMessage(error, "Couldn't start the search"));
    },
  });

  // Poll the job while it runs so the user sees progress.
  const jobQuery = useQuery({
    ...adLibraryQueryOptions.job(workspaceId ?? "", job?.id ?? ""),
    enabled:
      Boolean(workspaceId) &&
      Boolean(job?.id) &&
      (job?.status === "pending" || job?.status === "running"),
  });

  const liveJob = jobQuery.data ?? job;

  const advertisersQuery = useQuery({
    ...adLibraryQueryOptions.advertisers(workspaceId ?? "", {
      only_qualified: onlyQualified,
      page_size: 50,
    }),
    enabled: Boolean(workspaceId),
  });
  const advertisers = advertisersQuery.data?.items ?? [];

  return (
    <div className="mx-auto w-full max-w-3xl space-y-6 p-4 sm:p-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">Ad Library</h1>
        <p className="text-sm text-muted-foreground">
          Find advertisers already spending on ads who run the same creatives for
          months — the people you can help start proper creative testing.
        </p>
      </div>

      <AdLibrarySearchForm
        onSubmit={(values) => searchMutation.mutate(values)}
        isSubmitting={searchMutation.isPending}
      />

      {liveJob ? <JobStatusBanner job={liveJob} /> : null}

      <section className="space-y-3">
        <AdvertiserTableToolbar
          total={advertisersQuery.data?.total ?? 0}
          selectedCount={selectedIds.size}
          onlyQualified={onlyQualified}
          onToggleQualified={setOnlyQualified}
          onBulkPromote={() => bulkPromoteMutation.mutate()}
          isPromoting={bulkPromoteMutation.isPending}
        />
        {advertisersQuery.isLoading ? (
          <PageLoadingState message="Loading advertisers…" />
        ) : advertisersQuery.isError ? (
          <PageErrorState
            message="Couldn't load advertisers."
            onRetry={() => advertisersQuery.refetch()}
          />
        ) : advertisers.length === 0 ? (
          <PageEmptyState
            title="No tracked advertisers yet"
            description="Run a search above to start tracking advertisers."
          />
        ) : (
          <AdvertiserTable
            advertisers={advertisers}
            selectedIds={selectedIds}
            onToggleSelect={toggleSelect}
            onSelect={(advertiser) => {
              setSelected(advertiser);
              setDetailOpen(true);
            }}
          />
        )}
      </section>

      <MonitorsPanel workspaceId={workspaceId ?? ""} />

      <AdvertiserDetail
        workspaceId={workspaceId ?? ""}
        advertiserId={selected?.id ?? null}
        open={detailOpen}
        onOpenChange={setDetailOpen}
        onPromote={(advertiserId) => promoteMutation.mutate(advertiserId)}
        isPromoting={promoteMutation.isPending}
      />
    </div>
  );
}

function JobStatusBanner({ job }: { job: AdLibraryJob }) {
  const isRunning = job.status === "pending" || job.status === "running";
  const isDone = job.status === "succeeded";

  return (
    <Card>
      <CardContent className="flex items-center gap-3 pt-6">
        {isRunning ? (
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        ) : isDone ? (
          <CheckCircle2 className="h-5 w-5 text-emerald-500" />
        ) : (
          <Clock className="h-5 w-5 text-muted-foreground" />
        )}
        <div className="space-y-0.5">
          <p className="text-sm font-medium capitalize">{job.status}</p>
          <p className="text-xs text-muted-foreground">
            {isRunning
              ? "Scanning the ad library — this can take a moment."
              : isDone
                ? `Found ${job.discovered_count} advertiser${job.discovered_count === 1 ? "" : "s"}. View them below.`
                : (job.last_error ?? "Search finished.")}
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
