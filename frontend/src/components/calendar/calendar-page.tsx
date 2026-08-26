"use client";

/**
 * The calendar: one surface for everything that is scheduled.
 *
 * Appointments and field jobs used to live on two separate screens, which meant
 * nobody could answer "what is happening on Thursday?" without checking both and
 * reconciling them by hand. They are merged here into one month/week grid where
 * each day cell shows both species of work in time order.
 *
 * Visibility is enforced by the API, not by this component: below the dispatch
 * tier both list endpoints return only the entries the caller is tagged on, so
 * what a field worker sees here is already their own schedule. The controls that
 * belong to running the board — the unscheduled dispatch queue, "New job", and
 * the personal "Only mine" filter — are gated on `jobs:write` to match.
 */

import {
  ChevronLeft,
  ChevronRight,
  Plus,
  Calendar as CalendarIcon,
  Inbox,
  Settings,
  Wrench,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useState, useMemo } from "react";
import { toast } from "sonner";

import { AppointmentDetailsDialog } from "@/components/calendar/appointment-details-dialog";
import { CalendarEntryChip } from "@/components/calendar/calendar-entry-chip";
import { CalendarMonthView } from "@/components/calendar/calendar-month-view";
import { CalendarStatistics } from "@/components/calendar/calendar-statistics";
import { NewAppointmentDialog } from "@/components/calendar/new-appointment-dialog";
import { JobDetailDialog } from "@/components/jobs/job-detail-dialog";
import { NewJobDialog } from "@/components/jobs/new-job-dialog";
import { LocationFilter } from "@/components/locations/location-filter";
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
import { useAppointments, useDeleteAppointment } from "@/hooks/useAppointments";
import { useCapabilities } from "@/hooks/useCapabilities";
import { useJob, useJobs } from "@/hooks/useJobs";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import type { Job, JobListParams } from "@/lib/api/jobs";
import {
  STATUS_OPTIONS,
  buildAppointmentsQueryParams,
  getMonthRange,
  getWeekRange,
  statusFilterLabel,
  type StatusFilter,
} from "@/lib/calendar/calendar-derivations";
import {
  countByKind,
  entriesForDay,
  toCalendarEntries,
  todaysEntries,
  upcomingEntries,
  type CalendarEntry,
} from "@/lib/calendar/calendar-entries";
import {
  buildJobsQueryParams,
  jobStatusColors,
  jobStatusLabel,
} from "@/lib/jobs/job-derivations";
import { formatDate, addDays, addMonths, isSameDay } from "@/lib/utils/date";

type CalendarView = "month" | "week";

/**
 * The dispatch backlog is workspace-wide and independent of the visible range,
 * so it is fetched with its own status filter rather than derived from the
 * range-scoped list — whose `date_from`/`date_to` window excludes null-start
 * rows. Module-level so the query key stays referentially stable across renders.
 */
const UNSCHEDULED_QUEUE_PARAMS: JobListParams = { status: "unscheduled" };

export function CalendarPage({ initialJobId }: { initialJobId?: string } = {}) {
  const workspaceId = useWorkspaceId();
  const { can, tier } = useCapabilities();
  // jobs:write — owner/admin/manager/dispatcher. They run the board: the
  // unscheduled queue, job creation, and the personal "Only mine" filter are
  // theirs. Everyone below already receives a scoped list from the API, so a
  // filter for "only mine" would be a no-op switch, and the queue is dispatch
  // work they cannot act on.
  const canWriteJobs = can("jobs:write");
  const canViewReports = can("reports:view");

  const [currentDate, setCurrentDate] = useState(new Date());
  const [view, setView] = useState<CalendarView>("month");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("");
  const [locationId, setLocationId] = useState<string | undefined>(undefined);
  const [mineOnly, setMineOnly] = useState(false);
  const [expandedDayIso, setExpandedDayIso] = useState<string | null>(null);

  const [selectedAppointmentId, setSelectedAppointmentId] = useState<number | null>(null);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(initialJobId ?? null);
  const [isScheduleOpen, setIsScheduleOpen] = useState(false);
  const [isNewJobOpen, setIsNewJobOpen] = useState(false);

  // The visible range drives both fetches (query key + params) and the grid.
  // Month view spans whole weeks around the month; week view is Mon→Sun.
  const monthRange = useMemo(() => getMonthRange(currentDate), [currentDate]);
  const weekRange = useMemo(() => getWeekRange(currentDate), [currentDate]);
  const rangeStartIso =
    view === "month" ? monthRange.gridStartIso : weekRange.weekStartIso;
  const rangeEndIso = view === "month" ? monthRange.gridEndIso : weekRange.weekEndIso;

  // "Only mine" is a dispatcher's personal filter. Below that tier the API
  // already scopes both lists, so asking for it again would change nothing.
  const scopeToMine = canWriteJobs && mineOnly;

  // Both endpoint calls stay range-scoped and unfiltered; the shared status
  // control is applied to the merged datasets below. This matters because the
  // two APIs have overlapping but non-identical vocabularies (`in_progress` is
  // job-only, `no_show` is appointment-only), and a single server value cannot
  // express that union without making the other species disappear incorrectly.
  const appointmentParams = useMemo(
    () =>
      buildAppointmentsQueryParams(
        rangeStartIso,
        rangeEndIso,
        "",
        locationId,
        scopeToMine,
      ),
    [rangeStartIso, rangeEndIso, locationId, scopeToMine],
  );

  const jobParams = useMemo(
    () => buildJobsQueryParams(rangeStartIso, rangeEndIso, "", locationId, scopeToMine),
    [rangeStartIso, rangeEndIso, locationId, scopeToMine],
  );

  const appointmentsQuery = useAppointments(workspaceId ?? "", appointmentParams);
  const jobsQuery = useJobs(workspaceId ?? "", jobParams);
  // Dispatch-only: a field worker cannot schedule, so the backlog is not theirs.
  const unscheduledQuery = useJobs(
    workspaceId ?? "",
    UNSCHEDULED_QUEUE_PARAMS,
    canWriteJobs,
  );

  const deleteAppointmentMutation = useDeleteAppointment(workspaceId ?? "");

  const appointmentsList = useMemo(() => {
    const items = appointmentsQuery.data?.items ?? [];
    if (!statusFilter || statusFilter === "in_progress") {
      return statusFilter === "in_progress" ? [] : items;
    }
    return items.filter((appointment) => appointment.status === statusFilter);
  }, [appointmentsQuery.data?.items, statusFilter]);
  const jobsList = useMemo(() => {
    const items = jobsQuery.data?.items ?? [];
    if (!statusFilter || statusFilter === "no_show") {
      return statusFilter === "no_show" ? [] : items;
    }
    return items.filter((job) => job.status === statusFilter);
  }, [jobsQuery.data?.items, statusFilter]);
  const queue = useMemo(
    () => unscheduledQuery.data?.items ?? [],
    [unscheduledQuery.data?.items],
  );

  const entries = useMemo(
    () => toCalendarEntries(appointmentsList, jobsList),
    [appointmentsList, jobsList],
  );
  const counts = useMemo(() => countByKind(entries), [entries]);
  const todayEntries = useMemo(() => todaysEntries(entries), [entries]);
  const upcomingList = useMemo(() => upcomingEntries(entries), [entries]);

  const selectedAppointment = useMemo(
    () => appointmentsList.find((apt) => apt.id === selectedAppointmentId) ?? null,
    [appointmentsList, selectedAppointmentId],
  );

  // Ordinary selections resolve from the live lists. A `?job=` deep link (the
  // convert-quote flow lands on one) may point outside the visible range, so
  // that job is loaded directly.
  const listedSelectedJob = useMemo(
    () =>
      jobsList.find((job) => job.id === selectedJobId) ??
      queue.find((job) => job.id === selectedJobId) ??
      null,
    [jobsList, queue, selectedJobId],
  );
  const linkedJobQuery = useJob(
    workspaceId ?? "",
    selectedJobId ?? "",
    Boolean(selectedJobId) && listedSelectedJob === null,
  );
  const selectedJob = listedSelectedJob ?? linkedJobQuery.data ?? null;

  const openEntry = useCallback((entry: CalendarEntry) => {
    if (entry.kind === "appointment") setSelectedAppointmentId(entry.appointment.id);
    else setSelectedJobId(entry.job.id);
  }, []);

  // Changing the visible set closes any open entry, so a detail dialog cannot
  // resurrect when its row scrolls back into range. Doing it in the handlers
  // keeps this out of a render effect.
  const clearSelection = useCallback(() => {
    setSelectedAppointmentId(null);
    setSelectedJobId(null);
    setExpandedDayIso(null);
  }, []);

  const goToDate = useCallback(
    (next: Date) => {
      setCurrentDate(next);
      clearSelection();
    },
    [clearSelection],
  );
  const goToday = () => goToDate(new Date());
  const goPrev = () =>
    goToDate(view === "month" ? addMonths(currentDate, -1) : addDays(currentDate, -7));
  const goNext = () =>
    goToDate(view === "month" ? addMonths(currentDate, 1) : addDays(currentDate, 7));

  const changeView = useCallback(
    (next: CalendarView) => {
      setView(next);
      clearSelection();
    },
    [clearSelection],
  );
  const changeStatus = useCallback(
    (next: StatusFilter) => {
      setStatusFilter(next);
      clearSelection();
    },
    [clearSelection],
  );
  const changeLocation = useCallback(
    (next: string | undefined) => {
      setLocationId(next);
      clearSelection();
    },
    [clearSelection],
  );
  const changeMineOnly = useCallback(
    (checked: boolean) => {
      setMineOnly(checked);
      clearSelection();
    },
    [clearSelection],
  );

  const handleDeleteAppointment = (appointmentId: number) => {
    deleteAppointmentMutation.mutate(appointmentId, {
      onSuccess: () => {
        toast.success("Appointment cancelled");
        setSelectedAppointmentId(null);
      },
      onError: () => {
        toast.error("Failed to cancel appointment");
      },
    });
  };

  const isPending = appointmentsQuery.isPending || jobsQuery.isPending;
  const error = appointmentsQuery.error ?? jobsQuery.error;

  const retry = () => {
    void appointmentsQuery.refetch();
    void jobsQuery.refetch();
  };

  if (!workspaceId) {
    return <PageLoadingState className="h-96" message="Loading workspace…" />;
  }

  if (isPending) {
    return <PageLoadingState className="h-96" message="Loading schedule…" />;
  }

  if (error) {
    return (
      <PageErrorState
        className="h-96"
        message="Failed to load the schedule"
        onRetry={retry}
      />
    );
  }

  return (
    <div className="space-y-6 p-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Calendar</h1>
          <p className="text-muted-foreground">
            {canWriteJobs
              ? "Every appointment and job on one schedule"
              : "Your appointments and jobs"}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {tier !== "field" && (
            <Button variant="outline" asChild>
              <Link href="/settings">
                <Settings className="mr-2 size-4" />
                Settings
              </Link>
            </Button>
          )}
          {canWriteJobs && (
            <Button variant="outline" onClick={() => setIsNewJobOpen(true)}>
              <Wrench className="mr-2 size-4" />
              New job
            </Button>
          )}
          <Button onClick={() => setIsScheduleOpen(true)}>
            <Plus className="mr-2 size-4" />
            New appointment
          </Button>
        </div>
      </div>

      <NewAppointmentDialog open={isScheduleOpen} onOpenChange={setIsScheduleOpen} />

      {/* Mounted only for dispatchers: the create form's customer picker reads
          the workspace contact list, which is 403 for a field technician. */}
      {canWriteJobs && (
        <NewJobDialog
          workspaceId={workspaceId}
          open={isNewJobOpen}
          onOpenChange={setIsNewJobOpen}
        />
      )}

      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-2">
        <div
          className="flex flex-wrap items-center gap-1 rounded-lg bg-muted p-1"
          role="group"
          aria-label="Filter appointments by status"
        >
          {STATUS_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() => changeStatus(opt.value)}
              aria-pressed={statusFilter === opt.value}
              className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none ${
                statusFilter === opt.value
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
        <LocationFilter
          workspaceId={workspaceId}
          value={locationId}
          onChange={changeLocation}
        />
        {canWriteJobs && (
          <div className="flex items-center gap-2">
            <Switch id="mine-only" checked={mineOnly} onCheckedChange={changeMineOnly} />
            <Label htmlFor="mine-only" className="text-sm">
              Only mine
            </Label>
          </div>
        )}
        <span className="text-sm text-muted-foreground">
          {counts.appointments} appointment{counts.appointments !== 1 ? "s" : ""} ·{" "}
          {counts.jobs} job{counts.jobs !== 1 ? "s" : ""}
        </span>
      </div>

      {canViewReports ? <CalendarStatistics workspaceId={workspaceId} /> : null}

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Calendar */}
        <div className="space-y-4 lg:col-span-2">
          <Card>
            <CardHeader className="pb-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <CardTitle className="text-lg">
                  {formatDate(currentDate, { pattern: "MMMM yyyy" })}
                </CardTitle>
                <div className="flex items-center gap-2">
                  <div
                    className="flex items-center gap-1 rounded-lg bg-muted p-1"
                    role="group"
                    aria-label="Calendar view"
                  >
                    {(["month", "week"] as const).map((v) => (
                      <button
                        key={v}
                        type="button"
                        onClick={() => changeView(v)}
                        aria-pressed={view === v}
                        className={`rounded-md px-3 py-1 text-sm font-medium capitalize transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none ${
                          view === v
                            ? "bg-background text-foreground shadow-sm"
                            : "text-muted-foreground hover:text-foreground"
                        }`}
                      >
                        {v}
                      </button>
                    ))}
                  </div>
                  <div className="flex items-center gap-1">
                    <Button
                      variant="outline"
                      size="icon-sm"
                      onClick={goPrev}
                      aria-label={view === "month" ? "Previous month" : "Previous week"}
                    >
                      <ChevronLeft className="size-4" />
                    </Button>
                    <Button variant="outline" size="sm" onClick={goToday}>
                      Today
                    </Button>
                    <Button
                      variant="outline"
                      size="icon-sm"
                      onClick={goNext}
                      aria-label={view === "month" ? "Next month" : "Next week"}
                    >
                      <ChevronRight className="size-4" />
                    </Button>
                  </div>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              {view === "month" ? (
                <CalendarMonthView
                  weeks={monthRange.weeks}
                  monthDate={monthRange.monthDate}
                  entries={entries}
                  onSelect={openEntry}
                  expandedDayIso={expandedDayIso}
                  onExpandDay={setExpandedDayIso}
                />
              ) : (
                <>
                  {/* Week day headers */}
                  <div className="mb-2 hidden grid-cols-7 gap-2 md:grid">
                    {weekRange.weekDays.map((day) => (
                      <div
                        key={day.toISOString()}
                        className={`rounded-lg p-2 text-center ${
                          isSameDay(day, new Date())
                            ? "bg-primary text-primary-foreground"
                            : ""
                        }`}
                      >
                        <div className="text-xs font-medium">
                          {formatDate(day, { pattern: "EEE" })}
                        </div>
                        <div className="text-lg font-bold">
                          {formatDate(day, { pattern: "d" })}
                        </div>
                      </div>
                    ))}
                  </div>

                  {/* Both species of entry, one column per day */}
                  <div className="hidden min-h-[300px] grid-cols-7 gap-2 md:grid">
                    {weekRange.weekDays.map((day) => {
                      const dayEntries = entriesForDay(entries, day);
                      return (
                        <div
                          key={day.toISOString()}
                          className="min-h-[200px] rounded-lg border p-2"
                        >
                          <ScrollArea className="h-[260px]">
                            <div className="space-y-1">
                              {dayEntries.map((entry) => (
                                <CalendarEntryChip
                                  key={entry.key}
                                  entry={entry}
                                  onSelect={openEntry}
                                  density="stacked"
                                />
                              ))}
                            </div>
                          </ScrollArea>
                        </div>
                      );
                    })}
                  </div>

                  {/*
                    Phones get an agenda, not seven 40px columns. This is the
                    view a technician actually reads on site, so it keeps the
                    customer line and skips days with nothing on them.
                  */}
                  <div className="space-y-4 md:hidden">
                    {weekRange.weekDays
                      .map((day) => ({ day, dayEntries: entriesForDay(entries, day) }))
                      .filter(({ dayEntries }) => dayEntries.length > 0)
                      .map(({ day, dayEntries }) => (
                        <div key={day.toISOString()} className="space-y-1.5">
                          <h3
                            className={`text-sm font-semibold ${
                              isSameDay(day, new Date()) ? "text-primary" : ""
                            }`}
                          >
                            {formatDate(day, { pattern: "EEEE, MMMM d" })}
                          </h3>
                          {dayEntries.map((entry) => (
                            <CalendarEntryChip
                              key={entry.key}
                              entry={entry}
                              onSelect={openEntry}
                              showDetail
                              className="py-2 text-xs"
                            />
                          ))}
                        </div>
                      ))}
                    {entries.length === 0 && (
                      <p className="py-8 text-center text-sm text-muted-foreground">
                        Nothing scheduled this week
                      </p>
                    )}
                  </div>
                </>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Sidebar */}
        <div className="space-y-4">
          {/* Today */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <CalendarIcon className="size-5" />
                Today
              </CardTitle>
              <CardDescription>
                {formatDate(new Date(), { pattern: "EEEE, MMMM d" })}
              </CardDescription>
            </CardHeader>
            <CardContent>
              {todayEntries.length === 0 ? (
                <p className="py-4 text-center text-sm text-muted-foreground">
                  Nothing scheduled today
                </p>
              ) : (
                <div className="space-y-1.5">
                  {todayEntries.map((entry) => (
                    <CalendarEntryChip
                      key={entry.key}
                      entry={entry}
                      onSelect={openEntry}
                      showDetail
                    />
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Unscheduled dispatch queue — dispatchers only. */}
          {canWriteJobs && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Inbox className="size-5" />
                  Unscheduled
                </CardTitle>
                <CardDescription>Jobs waiting for a time window</CardDescription>
              </CardHeader>
              <CardContent>
                {unscheduledQuery.isPending ? (
                  <p className="py-4 text-center text-sm text-muted-foreground">
                    Loading queue…
                  </p>
                ) : queue.length === 0 ? (
                  <p className="py-4 text-center text-sm text-muted-foreground">
                    Nothing in the queue
                  </p>
                ) : (
                  <div className="space-y-2">
                    {queue.map((job: Job) => (
                      <button
                        key={job.id}
                        type="button"
                        onClick={() => setSelectedJobId(job.id)}
                        className="w-full space-y-1 rounded-lg border p-2 text-left transition-colors duration-150 hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none"
                      >
                        <p className="truncate text-sm font-medium">{job.title}</p>
                        <Badge
                          variant="outline"
                          className={`${jobStatusColors[job.status]} py-0 text-[10px]`}
                        >
                          {jobStatusLabel(job.status)}
                        </Badge>
                      </button>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          {/* Upcoming */}
          <Card>
            <CardHeader>
              <CardTitle>Upcoming</CardTitle>
              <CardDescription>Next in view</CardDescription>
            </CardHeader>
            <CardContent>
              {upcomingList.length === 0 ? (
                <p className="py-4 text-center text-sm text-muted-foreground">
                  Nothing upcoming in this range
                </p>
              ) : (
                <div className="space-y-1.5">
                  {upcomingList.slice(0, 5).map((entry) => (
                    <CalendarEntryChip
                      key={entry.key}
                      entry={entry}
                      onSelect={openEntry}
                      showDetail
                    />
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Range stats */}
          <Card>
            <CardHeader>
              <CardTitle>{view === "month" ? "This month" : "This week"}</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 gap-4 text-center">
                <div className="rounded-lg bg-muted/50 p-3">
                  <div className="text-2xl font-bold">{counts.appointments}</div>
                  <div className="text-xs text-muted-foreground">
                    {statusFilterLabel(statusFilter)} appointments
                  </div>
                </div>
                <div className="rounded-lg bg-muted/50 p-3">
                  <div className="text-2xl font-bold">{counts.jobs}</div>
                  <div className="text-xs text-muted-foreground">Jobs</div>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Shared detail dialogs — one per species, both driven by the grid. */}
      <AppointmentDetailsDialog
        key={`appointment-${selectedAppointmentId ?? "none"}`}
        appointment={selectedAppointment}
        workspaceId={workspaceId}
        open={selectedAppointmentId !== null}
        onOpenChange={(open) => !open && setSelectedAppointmentId(null)}
        onDelete={handleDeleteAppointment}
        onChanged={() => void appointmentsQuery.refetch()}
        deleting={deleteAppointmentMutation.isPending}
      />

      <JobDetailDialog
        key={`job-${selectedJobId ?? "none"}`}
        workspaceId={workspaceId}
        job={selectedJob}
        open={selectedJob !== null}
        onOpenChange={(next) => !next && setSelectedJobId(null)}
        readOnly={!canWriteJobs}
      />
    </div>
  );
}
