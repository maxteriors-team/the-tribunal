"use client";

import { AlertTriangle, CalendarClock, CircleDollarSign, Plus, Search } from "lucide-react";
import { useMemo, useState } from "react";

import { JobDetailDialog } from "@/components/jobs/job-detail-dialog";
import { NewJobDialog } from "@/components/jobs/new-job-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useJobs } from "@/hooks/useJobs";
import type { Job, JobStatus } from "@/lib/api/jobs";
import { jobStatusColors, jobStatusLabel } from "@/lib/jobs/job-derivations";
import { formatDate } from "@/lib/utils/date";
import { useWorkspace } from "@/providers/workspace-provider";

const STATUS_OPTIONS: Array<{ value: JobStatus | "all"; label: string }> = [
  { value: "all", label: "All statuses" },
  { value: "unscheduled", label: "Unscheduled" },
  { value: "scheduled", label: "Scheduled" },
  { value: "in_progress", label: "In progress" },
  { value: "completed", label: "Completed" },
  { value: "cancelled", label: "Cancelled" },
];

function isLate(job: Job) {
  return Boolean(
    job.scheduled_end &&
    new Date(job.scheduled_end).getTime() < Date.now() &&
    !["completed", "cancelled"].includes(job.status),
  );
}

export function JobsPage() {
  const { currentWorkspaceId } = useWorkspace();
  const workspaceId = currentWorkspaceId ?? "";
  const [status, setStatus] = useState<JobStatus | "all">("all");
  const [search, setSearch] = useState("");
  const [newJobOpen, setNewJobOpen] = useState(false);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const { data, isPending, isError, refetch } = useJobs(
    workspaceId,
    status === "all" ? {} : { status },
    Boolean(workspaceId),
  );

  const jobs = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return data?.items ?? [];
    return (data?.items ?? []).filter((job) =>
      [job.title, job.customer?.name, job.service_location?.address_line1]
        .filter(Boolean)
        .some((value) => value?.toLowerCase().includes(query)),
    );
  }, [data?.items, search]);

  const allJobs = data?.items ?? [];
  const selectedJob = allJobs.find((job) => job.id === selectedJobId) ?? null;
  const lateCount = allJobs.filter(isLate).length;
  const unscheduledCount = allJobs.filter((job) => job.status === "unscheduled").length;
  const activeCount = allJobs.filter((job) =>
    ["scheduled", "in_progress"].includes(job.status),
  ).length;

  if (!workspaceId) return null;

  return (
    <main className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Jobs</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Track scheduled work, assignments, and field progress.
          </p>
        </div>
        <Button onClick={() => setNewJobOpen(true)}>
          <Plus className="mr-2 size-4" />
          New job
        </Button>
      </div>

      <section aria-label="Job overview" className="mt-6 grid gap-3 sm:grid-cols-3">
        <button
          type="button"
          onClick={() => setStatus("all")}
          className="rounded-lg border bg-card p-4 text-left transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <span className="flex items-center gap-2 text-sm text-muted-foreground">
            <CalendarClock className="size-4" /> Active
          </span>
          <strong className="mt-2 block text-2xl">{activeCount}</strong>
        </button>
        <button
          type="button"
          onClick={() => setStatus("unscheduled")}
          className="rounded-lg border bg-card p-4 text-left transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <span className="flex items-center gap-2 text-sm text-muted-foreground">
            <CircleDollarSign className="size-4" /> Unscheduled
          </span>
          <strong className="mt-2 block text-2xl">{unscheduledCount}</strong>
        </button>
        <div className="rounded-lg border bg-card p-4">
          <span className="flex items-center gap-2 text-sm text-muted-foreground">
            <AlertTriangle className="size-4" /> Late
          </span>
          <strong className="mt-2 block text-2xl">{lateCount}</strong>
        </div>
      </section>

      <section
        className="mt-6 overflow-hidden rounded-lg border bg-card"
        aria-labelledby="all-jobs-heading"
      >
        <div className="flex flex-col gap-3 border-b p-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 id="all-jobs-heading" className="font-semibold">
              All jobs
            </h2>
            <p className="text-sm text-muted-foreground">{data?.total ?? 0} results</p>
          </div>
          <div className="flex flex-col gap-2 sm:flex-row">
            <Select value={status} onValueChange={(value) => setStatus(value as JobStatus | "all")}>
              <SelectTrigger className="w-full sm:w-44" aria-label="Filter by status">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {STATUS_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search jobs..."
                aria-label="Search jobs"
                className="pl-9 sm:w-64"
              />
            </div>
          </div>
        </div>

        {isPending ? (
          <div className="space-y-3 p-4" aria-label="Loading jobs">
            {Array.from({ length: 5 }, (_, index) => (
              <Skeleton key={index} className="h-14 w-full" />
            ))}
          </div>
        ) : isError ? (
          <div className="p-8 text-center">
            <p className="text-sm text-muted-foreground">Jobs could not be loaded.</p>
            <Button variant="outline" className="mt-3" onClick={() => void refetch()}>
              Retry
            </Button>
          </div>
        ) : jobs.length === 0 ? (
          <div className="p-10 text-center">
            <p className="font-medium">No jobs found</p>
            <p className="mt-1 text-sm text-muted-foreground">
              Adjust the filters or create a new job.
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-sm">
              <thead className="bg-muted/50 text-left text-xs uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="px-4 py-3 font-medium">Customer</th>
                  <th className="px-4 py-3 font-medium">Job</th>
                  <th className="px-4 py-3 font-medium">Property</th>
                  <th className="px-4 py-3 font-medium">Schedule</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                  <th className="px-4 py-3 font-medium">Assigned</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {jobs.map((job) => (
                  <tr key={job.id} className="transition-colors hover:bg-muted/40">
                    <td className="px-4 py-3 font-medium">
                      {job.customer?.name ?? "Unknown customer"}
                    </td>
                    <td className="px-4 py-3">
                      <button
                        type="button"
                        onClick={() => setSelectedJobId(job.id)}
                        className="max-w-xs text-left font-medium text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      >
                        {job.title}
                      </button>
                    </td>
                    <td className="max-w-64 truncate px-4 py-3 text-muted-foreground">
                      {job.service_location?.address_line1 ?? "Not set"}
                    </td>
                    <td className="px-4 py-3">
                      {job.scheduled_start
                        ? formatDate(job.scheduled_start, { pattern: "MMM d, yyyy" })
                        : "Schedule later"}
                    </td>
                    <td className="px-4 py-3">
                      <Badge variant="outline" className={jobStatusColors[job.status]}>
                        {isLate(job) ? "Late" : jobStatusLabel(job.status)}
                      </Badge>
                    </td>
                    <td className="px-4 py-3 text-muted-foreground">
                      {job.technicians?.length
                        ? job.technicians.map((technician) => technician.name).join(", ")
                        : "Unassigned"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <NewJobDialog workspaceId={workspaceId} open={newJobOpen} onOpenChange={setNewJobOpen} />
      <JobDetailDialog
        key={selectedJob?.id ?? "none"}
        workspaceId={workspaceId}
        job={selectedJob}
        open={Boolean(selectedJob)}
        onOpenChange={(open) => {
          if (!open) setSelectedJobId(null);
        }}
      />
    </main>
  );
}
