"use client";

import { ChevronLeft, ChevronRight, Plus, Clock, Inbox } from "lucide-react";
import { motion } from "motion/react";
import { useCallback, useMemo, useState } from "react";

import { JobDetailDialog } from "@/components/jobs/job-detail-dialog";
import { NewJobDialog } from "@/components/jobs/new-job-dialog";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { PageErrorState, PageLoadingState } from "@/components/ui/page-state";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Switch } from "@/components/ui/switch";
import { useJobs, useMyJobsCalendar } from "@/hooks/useJobs";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import type { Job, JobTechnician } from "@/lib/api/jobs";
import { getWeekRange } from "@/lib/calendar/calendar-derivations";
import {
  JOB_STATUS_OPTIONS,
  buildJobsQueryParams,
  jobStatusColors,
  jobStatusLabel,
  jobsForDay,
  technicianInitials,
  unscheduledJobs,
  type JobStatusFilter,
} from "@/lib/jobs/job-derivations";
import { addDays, formatDate, isSameDay } from "@/lib/utils/date";

function TechnicianChips({ technicians }: { technicians: JobTechnician[] }) {
  if (technicians.length === 0) {
    return <span className="text-[10px] text-muted-foreground">Unassigned</span>;
  }
  return (
    <div className="flex -space-x-1.5">
      {technicians.slice(0, 4).map((tech) => (
        <Avatar key={tech.id} className="size-5 ring-1 ring-background" title={tech.name}>
          <AvatarFallback
            className="text-[9px] text-white"
            style={{ backgroundColor: tech.color }}
          >
            {technicianInitials(tech.name)}
          </AvatarFallback>
        </Avatar>
      ))}
      {technicians.length > 4 && (
        <span className="ml-2 text-[10px] text-muted-foreground">
          +{technicians.length - 4}
        </span>
      )}
    </div>
  );
}

function JobCard({ job, onSelect }: { job: Job; onSelect: (job: Job) => void }) {
  return (
    <motion.button
      type="button"
      onClick={() => onSelect(job)}
      className="w-full text-left p-2 rounded-md bg-primary/10 hover:bg-primary/20 transition-colors space-y-1"
      whileHover={{ scale: 1.02 }}
      whileTap={{ scale: 0.98 }}
    >
      <p className="text-xs font-medium truncate">{job.title}</p>
      {job.scheduled_start && (
        <p className="text-[11px] text-muted-foreground">
          {formatDate(job.scheduled_start, { pattern: "h:mm a" })}
        </p>
      )}
      <Badge variant="outline" className={`${jobStatusColors[job.status]} text-[10px] py-0`}>
        {jobStatusLabel(job.status)}
      </Badge>
      <div className="pt-0.5">
        <TechnicianChips technicians={job.technicians ?? []} />
      </div>
    </motion.button>
  );
}

export function JobsCalendar() {
  const workspaceId = useWorkspaceId();
  const [currentDate, setCurrentDate] = useState(new Date());
  const [statusFilter, setStatusFilter] = useState<JobStatusFilter>("");
  const [mineOnly, setMineOnly] = useState(false);
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);

  const { weekStart, weekStartIso, weekEndIso, weekDays } = useMemo(
    () => getWeekRange(currentDate),
    [currentDate],
  );

  const queryParams = useMemo(
    () => buildJobsQueryParams(weekStartIso, weekEndIso, statusFilter),
    [weekStartIso, weekEndIso, statusFilter],
  );

  const boardQuery = useJobs(workspaceId ?? "", queryParams, !mineOnly);
  const mineQuery = useMyJobsCalendar(
    workspaceId ?? "",
    { date_from: weekStartIso, date_to: weekEndIso },
    mineOnly,
  );

  const activeQuery = mineOnly ? mineQuery : boardQuery;
  const jobs = useMemo(() => activeQuery.data?.items ?? [], [activeQuery.data?.items]);
  const queue = useMemo(() => unscheduledJobs(jobs), [jobs]);

  // Resolve the open job from the live list so the detail dialog reflects edits
  // after a refetch, and closes itself if the job is deleted or filtered out.
  const selectedJob = useMemo(
    () => jobs.find((job) => job.id === selectedJobId) ?? null,
    [jobs, selectedJobId],
  );

  // Changing the visible set (week, status, or the "my jobs" scope) clears any
  // open job so the detail dialog can't resurrect when that job scrolls back
  // into range. Resetting selection here (in the event handlers that mutate the
  // query) keeps the close logic out of a render effect.
  const goToWeek = useCallback((date: Date) => {
    setCurrentDate(date);
    setSelectedJobId(null);
  }, []);
  const changeStatus = useCallback((value: JobStatusFilter) => {
    setStatusFilter(value);
    setSelectedJobId(null);
  }, []);
  const changeMineOnly = useCallback((checked: boolean) => {
    setMineOnly(checked);
    setSelectedJobId(null);
  }, []);

  if (!workspaceId) {
    return <PageLoadingState className="h-96" message="Loading workspace…" />;
  }

  if (activeQuery.isPending) {
    return <PageLoadingState className="h-96" message="Loading jobs…" />;
  }

  if (activeQuery.error) {
    return (
      <PageErrorState
        className="h-96"
        message="Failed to load jobs"
        onRetry={() => void activeQuery.refetch()}
      />
    );
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Jobs</h1>
          <p className="text-muted-foreground">
            Dispatch field work and see it on assigned workers&apos; calendars
          </p>
        </div>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <Switch id="mine-only" checked={mineOnly} onCheckedChange={changeMineOnly} />
            <Label htmlFor="mine-only" className="text-sm">
              My jobs
            </Label>
          </div>
          <Button onClick={() => setIsCreateOpen(true)}>
            <Plus className="mr-2 size-4" />
            New Job
          </Button>
        </div>
      </div>

      <NewJobDialog
        workspaceId={workspaceId}
        open={isCreateOpen}
        onOpenChange={setIsCreateOpen}
      />

      <JobDetailDialog
        key={selectedJob?.id ?? "none"}
        workspaceId={workspaceId}
        job={selectedJob}
        open={selectedJob !== null}
        onOpenChange={(next) => !next && setSelectedJobId(null)}
        readOnly={mineOnly}
      />

      {/* Status filter (board view only) */}
      {!mineOnly && (
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1 bg-muted rounded-lg p-1 flex-wrap">
            {JOB_STATUS_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                onClick={() => changeStatus(opt.value)}
                className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
                  statusFilter === opt.value
                    ? "bg-background shadow-sm text-foreground"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
          <span className="text-sm text-muted-foreground">
            {jobs.length} job{jobs.length !== 1 ? "s" : ""}
          </span>
        </div>
      )}

      {/* Mobile agenda (single column) — the field/worker experience. The
          7-column week grid below is desktop-only. */}
      <div className="space-y-5 lg:hidden">
        <div className="flex items-center justify-between">
          <span className="text-sm font-semibold">
            {formatDate(weekStart, { pattern: "MMMM yyyy" })}
          </span>
          <div className="flex items-center gap-1">
            <Button
              variant="outline"
              size="icon-sm"
              onClick={() => goToWeek(addDays(currentDate, -7))}
              aria-label="Previous week"
            >
              <ChevronLeft className="size-4" />
            </Button>
            <Button variant="outline" size="sm" onClick={() => goToWeek(new Date())}>
              Today
            </Button>
            <Button
              variant="outline"
              size="icon-sm"
              onClick={() => goToWeek(addDays(currentDate, 7))}
              aria-label="Next week"
            >
              <ChevronRight className="size-4" />
            </Button>
          </div>
        </div>

        {weekDays.map((day) => {
          const dayJobs = jobsForDay(jobs, day);
          if (dayJobs.length === 0) return null;
          return (
            <div key={day.toISOString()} className="space-y-2">
              <div
                className={`text-sm font-semibold ${
                  isSameDay(day, new Date()) ? "text-primary" : ""
                }`}
              >
                {formatDate(day, { pattern: "EEEE, MMM d" })}
              </div>
              <div className="space-y-1.5">
                {dayJobs.map((job) => (
                  <JobCard
                    key={job.id}
                    job={job}
                    onSelect={(selected) => setSelectedJobId(selected.id)}
                  />
                ))}
              </div>
            </div>
          );
        })}

        {queue.length > 0 && (
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-sm font-semibold">
              <Inbox className="size-4" />
              Unscheduled
            </div>
            <div className="space-y-1.5">
              {queue.map((job) => (
                <JobCard
                  key={job.id}
                  job={job}
                  onSelect={(selected) => setSelectedJobId(selected.id)}
                />
              ))}
            </div>
          </div>
        )}

        {jobs.length === 0 && (
          <p className="py-8 text-center text-sm text-muted-foreground">
            No jobs this week.
          </p>
        )}
      </div>

      <div className="hidden gap-6 lg:grid lg:grid-cols-4">
        {/* Week grid */}
        <div className="lg:col-span-3 space-y-4">
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-lg">
                  {formatDate(weekStart, { pattern: "MMMM yyyy" })}
                </CardTitle>
                <div className="flex items-center gap-1">
                  <Button
                    variant="outline"
                    size="icon-sm"
                    onClick={() => goToWeek(addDays(currentDate, -7))}
                    aria-label="Previous week"
                  >
                    <ChevronLeft className="size-4" />
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => goToWeek(new Date())}
                  >
                    Today
                  </Button>
                  <Button
                    variant="outline"
                    size="icon-sm"
                    onClick={() => goToWeek(addDays(currentDate, 7))}
                    aria-label="Next week"
                  >
                    <ChevronRight className="size-4" />
                  </Button>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              {/* Day headers */}
              <div className="grid grid-cols-7 gap-2 mb-2">
                {weekDays.map((day) => (
                  <div
                    key={day.toISOString()}
                    className={`text-center p-2 rounded-lg ${
                      isSameDay(day, new Date()) ? "bg-primary text-primary-foreground" : ""
                    }`}
                  >
                    <div className="text-xs font-medium">
                      {formatDate(day, { pattern: "EEE" })}
                    </div>
                    <div className="text-lg font-bold">{formatDate(day, { pattern: "d" })}</div>
                  </div>
                ))}
              </div>

              {/* Day columns */}
              <div className="grid grid-cols-7 gap-2 min-h-[300px]">
                {weekDays.map((day) => {
                  const dayJobs = jobsForDay(jobs, day);
                  return (
                    <div key={day.toISOString()} className="border rounded-lg p-2 min-h-[200px]">
                      <ScrollArea className="h-[260px]">
                        <div className="space-y-1.5">
                          {dayJobs.map((job) => (
                            <JobCard
                              key={job.id}
                              job={job}
                              onSelect={(selected) => setSelectedJobId(selected.id)}
                            />
                          ))}
                        </div>
                      </ScrollArea>
                    </div>
                  );
                })}
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Unscheduled queue */}
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Inbox className="size-5" />
                Unscheduled
              </CardTitle>
              <CardDescription>Jobs waiting for a time window</CardDescription>
            </CardHeader>
            <CardContent>
              {queue.length === 0 ? (
                <p className="text-sm text-muted-foreground text-center py-4">
                  Nothing in the queue
                </p>
              ) : (
                <div className="space-y-2">
                  {queue.map((job) => (
                    <button
                      key={job.id}
                      type="button"
                      onClick={() => setSelectedJobId(job.id)}
                      className="w-full text-left p-2 rounded-lg border space-y-1 hover:bg-muted/50 transition-colors"
                    >
                      <p className="text-sm font-medium truncate">{job.title}</p>
                      <div className="flex items-center justify-between">
                        <Badge
                          variant="outline"
                          className={`${jobStatusColors[job.status]} text-[10px] py-0`}
                        >
                          {jobStatusLabel(job.status)}
                        </Badge>
                        <TechnicianChips technicians={job.technicians ?? []} />
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Clock className="size-5" />
                This week
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{jobs.length}</div>
              <p className="text-xs text-muted-foreground">
                {mineOnly ? "Assigned to you" : "Total jobs"}
              </p>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
