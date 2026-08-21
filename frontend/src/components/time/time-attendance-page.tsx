"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Clock3,
  Download,
  FileClock,
  Loader2,
  Pause,
  Pencil,
  Play,
  Plus,
  ShieldCheck,
  Timer,
  UserRound,
  UsersRound,
  XCircle,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import {
  AttendanceEntryEditDialog,
  AttendanceEntryVoidDialog,
  AttendanceManualEntryDialog,
} from "@/components/time/attendance-entry-dialogs";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PageEmptyState, PageErrorState, PageLoadingState } from "@/components/ui/page-state";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useCapabilities } from "@/hooks/useCapabilities";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import {
  attendanceApi,
  type AttendanceAdminCreateRequest,
  type AttendanceEntry,
  type AttendanceUpdateRequest,
} from "@/lib/api/attendance";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { useWorkspace } from "@/providers/workspace-provider";

type AttendanceManualEntry = Omit<AttendanceAdminCreateRequest, "request_id">;
type AttendanceCorrection = Omit<AttendanceUpdateRequest, "request_id">;

const MAX_RANGE_DAYS = 62;

function dateInTimezone(date: Date, timezone: string): string {
  try {
    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone: timezone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).formatToParts(date);
    const value = Object.fromEntries(parts.map((part) => [part.type, part.value]));
    return `${value.year}-${value.month}-${value.day}`;
  } catch {
    return date.toISOString().slice(0, 10);
  }
}

function initialRange(timezone: string): { dateFrom: string; dateTo: string } {
  const dateTo = dateInTimezone(new Date(), timezone);
  return { dateFrom: `${dateTo.slice(0, 7)}-01`, dateTo };
}

function rangeError(dateFrom: string, dateTo: string): string | null {
  const start = new Date(`${dateFrom}T00:00:00`);
  const end = new Date(`${dateTo}T00:00:00`);
  if (!dateFrom || !dateTo || Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) {
    return "Choose a start and end date.";
  }
  if (start > end) return "The start date must be before the end date.";
  const days = Math.floor((end.getTime() - start.getTime()) / 86_400_000) + 1;
  return days > MAX_RANGE_DAYS ? `Choose ${MAX_RANGE_DAYS} days or fewer.` : null;
}

function formatDuration(totalSeconds: number): string {
  const safeSeconds = Math.max(0, Math.round(totalSeconds));
  const hours = Math.floor(safeSeconds / 3600);
  const minutes = Math.floor((safeSeconds % 3600) / 60);
  return `${hours}h ${String(minutes).padStart(2, "0")}m`;
}

function formatClockDuration(totalSeconds: number): string {
  const safeSeconds = Math.max(0, Math.round(totalSeconds));
  const hours = Math.floor(safeSeconds / 3600);
  const minutes = Math.floor((safeSeconds % 3600) / 60);
  const seconds = safeSeconds % 60;
  return [hours, minutes, seconds].map((value) => String(value).padStart(2, "0")).join(":");
}

function formatInWorkspace(value: string, timezone: string, includeDate = true): string {
  return new Intl.DateTimeFormat(undefined, {
    timeZone: timezone,
    ...(includeDate ? { month: "short", day: "numeric", year: "numeric" } : undefined),
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

function statusLabel(status: AttendanceEntry["status"], isPaused = false): string {
  if (status === "open") return isPaused ? "Paused" : "Clocked in";
  if (status === "void") return "Voided";
  return "Complete";
}

function StatusBadge({
  status,
  isPaused = false,
}: {
  status: AttendanceEntry["status"];
  isPaused?: boolean;
}) {
  return (
    <Badge variant={status === "void" ? "destructive" : "outline"}>
      {statusLabel(status, isPaused)}
    </Badge>
  );
}

interface TimeClockCardProps {
  openEntry: AttendanceEntry | null;
  totalSeconds: number;
  timezone: string;
  pendingAction: "clock" | "pause" | null;
  onToggle: () => void;
  onPauseToggle: () => void;
}

function TimeClockCard({
  openEntry,
  totalSeconds,
  timezone,
  pendingAction,
  onToggle,
  onPauseToggle,
}: TimeClockCardProps) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!openEntry || openEntry.is_paused) return;
    const interval = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(interval);
  }, [openEntry]);

  const runningSeconds = openEntry
    ? openEntry.duration_seconds +
      (openEntry.is_paused
        ? 0
        : Math.max(0, Math.floor((now - new Date(openEntry.calculated_at).getTime()) / 1000)))
    : 0;
  const pending = pendingAction !== null;

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2">
              <Clock3 className="size-5" aria-hidden="true" />
              My shift
            </CardTitle>
            <CardDescription className="mt-1">
              Times display in {timezone || "the workspace timezone"}.
            </CardDescription>
          </div>
          <Badge variant="outline">
            {openEntry ? (openEntry.is_paused ? "Paused" : "Clocked in") : "Clocked out"}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-5">
        <div aria-live="polite">
          <p className="text-sm text-muted-foreground">
            {openEntry
              ? openEntry.is_paused && openEntry.pause_started_at
                ? `Paused ${formatInWorkspace(openEntry.pause_started_at, timezone)}`
                : `Started ${formatInWorkspace(openEntry.started_at, timezone)}`
              : "You are not currently clocked in."}
          </p>
          <p className="mt-1 font-mono text-4xl font-semibold tabular-nums tracking-tight">
            {openEntry ? formatClockDuration(runningSeconds) : formatDuration(totalSeconds)}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            {openEntry
              ? openEntry.is_paused
                ? "Worked time is paused"
                : "Current worked time"
              : "Recorded in the selected date range"}
          </p>
        </div>
        {openEntry ? (
          <div className="flex flex-col gap-2 sm:flex-row">
            <Button
              size="lg"
              variant={openEntry.is_paused ? "default" : "outline"}
              className="w-full sm:w-auto"
              onClick={onPauseToggle}
              disabled={pending}
            >
              {pendingAction === "pause" ? (
                <Loader2 className="size-4 animate-spin" aria-hidden="true" />
              ) : openEntry.is_paused ? (
                <Play className="size-4" aria-hidden="true" />
              ) : (
                <Pause className="size-4" aria-hidden="true" />
              )}
              {pendingAction === "pause" ? "Saving…" : openEntry.is_paused ? "Resume" : "Pause"}
            </Button>
            <Button
              size="lg"
              variant="destructive"
              className="w-full sm:w-auto"
              onClick={onToggle}
              disabled={pending}
            >
              {pendingAction === "clock" ? (
                <Loader2 className="size-4 animate-spin" aria-hidden="true" />
              ) : (
                <Timer className="size-4" aria-hidden="true" />
              )}
              {pendingAction === "clock" ? "Saving…" : "Clock out"}
            </Button>
          </div>
        ) : (
          <Button
            size="lg"
            className="w-full sm:w-auto"
            onClick={onToggle}
            disabled={pending}
          >
            {pendingAction === "clock" ? (
              <Loader2 className="size-4 animate-spin" aria-hidden="true" />
            ) : (
              <Timer className="size-4" aria-hidden="true" />
            )}
            {pendingAction === "clock" ? "Saving…" : "Clock in"}
          </Button>
        )}
        <p className="text-xs text-muted-foreground">
          Pause stops the worked-time counter. This clock records timestamps and notes; it does not
          track your location, screen, or activity.
        </p>
      </CardContent>
    </Card>
  );
}

interface AttendanceEntriesProps {
  entries: AttendanceEntry[];
  timezone: string;
  showEmployee?: boolean;
  canManage?: boolean;
  onEdit?: (entry: AttendanceEntry) => void;
  onVoid?: (entry: AttendanceEntry) => void;
}

function AttendanceEntries({
  entries,
  timezone,
  showEmployee = false,
  canManage = false,
  onEdit,
  onVoid,
}: AttendanceEntriesProps) {
  if (entries.length === 0) {
    return (
      <PageEmptyState
        className="min-h-[200px]"
        title="No recorded hours"
        description="No shifts start inside this date range."
        icon={<FileClock className="size-8" aria-hidden="true" />}
      />
    );
  }

  const actions = (entry: AttendanceEntry) =>
    canManage && entry.status !== "void" ? (
      <div className="flex justify-end gap-1">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => onEdit?.(entry)}
          disabled={entry.status === "open"}
          title={entry.status === "open" ? "Clock out before correcting this entry" : undefined}
        >
          <Pencil className="size-4" aria-hidden="true" />
          Edit
        </Button>
        <Button type="button" variant="ghost" size="sm" onClick={() => onVoid?.(entry)}>
          <XCircle className="size-4" aria-hidden="true" />
          Void
        </Button>
      </div>
    ) : null;

  return (
    <>
      <div className="hidden overflow-x-auto rounded-md border md:block">
        <Table>
          <TableHeader>
            <TableRow>
              {showEmployee ? <TableHead>Employee</TableHead> : null}
              <TableHead>Clock in</TableHead>
              <TableHead>Clock out</TableHead>
              <TableHead className="text-right">Hours</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Source</TableHead>
              {canManage ? <TableHead className="text-right">Actions</TableHead> : null}
            </TableRow>
          </TableHeader>
          <TableBody>
            {entries.map((entry) => (
              <TableRow
                key={entry.id}
                className={entry.status === "void" ? "text-muted-foreground" : undefined}
              >
                {showEmployee ? (
                  <TableCell>
                    <p className="font-medium">{entry.employee_name}</p>
                    <p className="text-xs text-muted-foreground">{entry.employee_email}</p>
                  </TableCell>
                ) : null}
                <TableCell>{formatInWorkspace(entry.started_at, timezone)}</TableCell>
                <TableCell>
                  {entry.ended_at
                    ? formatInWorkspace(entry.ended_at, timezone, false)
                    : entry.is_paused
                      ? "Paused"
                      : "Running"}
                </TableCell>
                <TableCell className="text-right font-mono tabular-nums">
                  {entry.status === "void" ? "Excluded" : formatDuration(entry.duration_seconds)}
                  {entry.status !== "void" && entry.paused_seconds > 0 ? (
                    <span className="block text-xs text-muted-foreground">
                      {formatDuration(entry.paused_seconds)} paused
                    </span>
                  ) : null}
                </TableCell>
                <TableCell>
                  <StatusBadge status={entry.status} isPaused={entry.is_paused} />
                </TableCell>
                <TableCell className="capitalize">{entry.source}</TableCell>
                {canManage ? <TableCell>{actions(entry)}</TableCell> : null}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <div className="grid gap-3 md:hidden">
        {entries.map((entry) => (
          <article key={entry.id} className="space-y-3 rounded-lg border p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                {showEmployee ? <p className="font-medium">{entry.employee_name}</p> : null}
                <p className="text-sm text-muted-foreground">
                  {formatInWorkspace(entry.started_at, timezone)}
                </p>
              </div>
              <StatusBadge status={entry.status} isPaused={entry.is_paused} />
            </div>
            <dl className="grid grid-cols-2 gap-3 text-sm">
              <div>
                <dt className="text-muted-foreground">Clock out</dt>
                <dd>
                  {entry.ended_at
                    ? formatInWorkspace(entry.ended_at, timezone, false)
                    : entry.is_paused
                      ? "Paused"
                      : "Running"}
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Recorded</dt>
                <dd className="font-mono tabular-nums">
                  {entry.status === "void" ? "Excluded" : formatDuration(entry.duration_seconds)}
                </dd>
              </div>
              {entry.status !== "void" && entry.paused_seconds > 0 ? (
                <div>
                  <dt className="text-muted-foreground">Paused</dt>
                  <dd className="font-mono tabular-nums">
                    {formatDuration(entry.paused_seconds)}
                  </dd>
                </div>
              ) : null}
            </dl>
            {entry.note ? <p className="text-sm text-muted-foreground">{entry.note}</p> : null}
            {actions(entry)}
          </article>
        ))}
      </div>
    </>
  );
}

function SummaryCard({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
}) {
  return (
    <Card>
      <CardContent className="flex items-center gap-3 p-4">
        <div className="text-muted-foreground">{icon}</div>
        <div>
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            {label}
          </p>
          <p className="mt-0.5 text-xl font-semibold tabular-nums">{value}</p>
        </div>
      </CardContent>
    </Card>
  );
}

export function TimeAttendancePage() {
  const workspaceId = useWorkspaceId();
  const { currentWorkspace } = useWorkspace();
  const { can } = useCapabilities();
  const queryClient = useQueryClient();
  const workspaceSettings = currentWorkspace?.workspace.settings as
    | Record<string, unknown>
    | null
    | undefined;
  const configuredTimezone =
    typeof workspaceSettings?.timezone === "string" ? workspaceSettings.timezone : "UTC";
  const [{ dateFrom, dateTo }, setRange] = useState(() => initialRange(configuredTimezone));
  const rangeWorkspaceId = useRef<string | null>(null);
  const [tab, setTab] = useState("mine");
  const [manualEntryOpen, setManualEntryOpen] = useState(false);
  const [editingEntry, setEditingEntry] = useState<AttendanceEntry | null>(null);
  const [voidingEntry, setVoidingEntry] = useState<AttendanceEntry | null>(null);
  const canUse = can("attendance:use");
  const canManage = can("attendance:manage");
  const invalidRange = rangeError(dateFrom, dateTo);
  const params = useMemo(() => ({ date_from: dateFrom, date_to: dateTo }), [dateFrom, dateTo]);

  useEffect(() => {
    if (!workspaceId || rangeWorkspaceId.current === workspaceId) return;
    rangeWorkspaceId.current = workspaceId;
    setRange(initialRange(configuredTimezone));
  }, [configuredTimezone, workspaceId]);

  const mineQuery = useQuery({
    queryKey: queryKeys.attendance.mine(workspaceId ?? "", params),
    queryFn: () => attendanceApi.mine(workspaceId!, params),
    enabled: Boolean(workspaceId && canUse && !invalidRange),
  });

  const teamQuery = useQuery({
    queryKey: queryKeys.attendance.team(workspaceId ?? "", params),
    queryFn: () => attendanceApi.team(workspaceId!, params),
    enabled: Boolean(workspaceId && canManage && tab === "team" && !invalidRange),
  });

  const refreshAttendance = async () => {
    if (!workspaceId) return;
    await queryClient.invalidateQueries({ queryKey: queryKeys.attendance.all(workspaceId) });
  };

  const clockMutation = useMutation({
    mutationFn: () => {
      if (!workspaceId) throw new Error("No workspace selected");
      const request = { request_id: crypto.randomUUID() };
      return mineQuery.data?.open_entry
        ? attendanceApi.clockOut(workspaceId, request)
        : attendanceApi.clockIn(workspaceId, request);
    },
    onSuccess: async (entry) => {
      toast.success(entry.status === "open" ? "Clocked in" : "Clocked out");
      await refreshAttendance();
    },
    onError: (error) => toast.error(getApiErrorMessage(error, "Could not update the time clock.")),
  });

  const pauseMutation = useMutation({
    mutationFn: () => {
      if (!workspaceId) throw new Error("No workspace selected");
      const request = { request_id: crypto.randomUUID() };
      return mineQuery.data?.open_entry?.is_paused
        ? attendanceApi.resume(workspaceId, request)
        : attendanceApi.pause(workspaceId, request);
    },
    onSuccess: async (entry) => {
      toast.success(entry.is_paused ? "Shift paused" : "Shift resumed");
      await refreshAttendance();
    },
    onError: (error) =>
      toast.error(getApiErrorMessage(error, "Could not pause or resume the time clock.")),
  });

  const createMutation = useMutation({
    mutationFn: (entry: AttendanceManualEntry) => {
      if (!workspaceId) throw new Error("No workspace selected");
      return attendanceApi.createEntry(workspaceId, {
        request_id: crypto.randomUUID(),
        ...entry,
      });
    },
    onSuccess: async () => {
      setManualEntryOpen(false);
      toast.success("Recorded hours added");
      await refreshAttendance();
    },
    onError: (error) => toast.error(getApiErrorMessage(error, "Could not add recorded hours.")),
  });

  const updateMutation = useMutation({
    mutationFn: ({ entryId, update }: { entryId: string; update: AttendanceCorrection }) => {
      if (!workspaceId) throw new Error("No workspace selected");
      return attendanceApi.updateEntry(workspaceId, entryId, {
        request_id: crypto.randomUUID(),
        ...update,
      });
    },
    onSuccess: async () => {
      setEditingEntry(null);
      toast.success("Time entry corrected");
      await refreshAttendance();
    },
    onError: (error) => toast.error(getApiErrorMessage(error, "Could not correct the time entry.")),
  });

  const voidMutation = useMutation({
    mutationFn: ({ entryId, reason }: { entryId: string; reason: string }) => {
      if (!workspaceId) throw new Error("No workspace selected");
      return attendanceApi.voidEntry(workspaceId, entryId, {
        request_id: crypto.randomUUID(),
        reason,
      });
    },
    onSuccess: async () => {
      setVoidingEntry(null);
      toast.success("Time entry voided");
      await refreshAttendance();
    },
    onError: (error) => toast.error(getApiErrorMessage(error, "Could not void the time entry.")),
  });

  const exportMutation = useMutation({
    mutationFn: () => {
      if (!workspaceId) throw new Error("No workspace selected");
      return attendanceApi.exportCsv(workspaceId, {
        request_id: crypto.randomUUID(),
        ...params,
      });
    },
    onSuccess: ({ blob, filename }) => {
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
      toast.success("Payroll CSV downloaded");
    },
    onError: (error) => toast.error(getApiErrorMessage(error, "Could not export payroll hours.")),
  });

  if (!canUse) {
    return (
      <PageErrorState title="Access denied" message="Your role cannot use Time & Attendance." />
    );
  }
  if (!workspaceId || (mineQuery.isLoading && !mineQuery.data)) {
    return <PageLoadingState message="Loading recorded hours…" />;
  }
  if (mineQuery.isError) {
    return (
      <PageErrorState
        title="Hours could not be loaded"
        message={getApiErrorMessage(mineQuery.error, "Try again in a moment.")}
        onRetry={() => void mineQuery.refetch()}
      />
    );
  }

  const mine = mineQuery.data;

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <TimeClockCard
        openEntry={mine?.open_entry ?? null}
        totalSeconds={mine?.total_seconds ?? 0}
        timezone={mine?.timezone ?? "UTC"}
        pendingAction={
          clockMutation.isPending ? "clock" : pauseMutation.isPending ? "pause" : null
        }
        onToggle={() => clockMutation.mutate()}
        onPauseToggle={() => pauseMutation.mutate()}
      />

      <div className="flex flex-col gap-3 rounded-lg border p-4 sm:flex-row sm:items-end">
        <div className="flex-1 space-y-2">
          <Label htmlFor="attendance-date-from">From</Label>
          <Input
            id="attendance-date-from"
            type="date"
            value={dateFrom}
            max={dateTo}
            onChange={(event) =>
              setRange((current) => ({ ...current, dateFrom: event.target.value }))
            }
          />
        </div>
        <div className="flex-1 space-y-2">
          <Label htmlFor="attendance-date-to">Through</Label>
          <Input
            id="attendance-date-to"
            type="date"
            value={dateTo}
            min={dateFrom}
            onChange={(event) =>
              setRange((current) => ({ ...current, dateTo: event.target.value }))
            }
          />
        </div>
        <p className="pb-2 text-xs text-muted-foreground sm:max-w-xs">
          Shifts count toward the local date when they started. Maximum {MAX_RANGE_DAYS} days.
        </p>
      </div>

      {invalidRange ? (
        <Alert variant="destructive">
          <AlertTitle>Check the date range</AlertTitle>
          <AlertDescription>{invalidRange}</AlertDescription>
        </Alert>
      ) : null}

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="mine">
            <UserRound className="size-4" aria-hidden="true" />
            My hours
          </TabsTrigger>
          {canManage ? (
            <TabsTrigger value="team">
              <UsersRound className="size-4" aria-hidden="true" />
              Team hours
            </TabsTrigger>
          ) : null}
        </TabsList>

        <TabsContent value="mine" className="mt-4 space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <SummaryCard
              icon={<Timer className="size-5" aria-hidden="true" />}
              label="Recorded"
              value={formatDuration(mine?.total_seconds ?? 0)}
            />
            <SummaryCard
              icon={<FileClock className="size-5" aria-hidden="true" />}
              label="Entries"
              value={String(mine?.entries.length ?? 0)}
            />
          </div>
          <AttendanceEntries entries={mine?.entries ?? []} timezone={mine?.timezone ?? "UTC"} />
        </TabsContent>

        {canManage ? (
          <TabsContent value="team" className="mt-4 space-y-4">
            <Alert>
              <ShieldCheck className="size-4" aria-hidden="true" />
              <AlertTitle>Payroll review required</AlertTitle>
              <AlertDescription>
                The Generic payroll CSV separates gross, paused, and worked hours for completed
                shifts. Open and voided entries are excluded. Review whether paused time is paid,
                then classify overtime, leave, rates, and earning codes before running payroll.
              </AlertDescription>
            </Alert>

            {teamQuery.isLoading ? <PageLoadingState message="Loading team hours…" /> : null}
            {teamQuery.isError ? (
              <PageErrorState
                title="Team hours could not be loaded"
                message={getApiErrorMessage(teamQuery.error, "Try again in a moment.")}
                onRetry={() => void teamQuery.refetch()}
              />
            ) : null}
            {teamQuery.data ? (
              <>
                <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
                  <div className="grid flex-1 gap-3 sm:grid-cols-3">
                    <SummaryCard
                      icon={<Timer className="size-5" aria-hidden="true" />}
                      label="Team hours"
                      value={formatDuration(teamQuery.data.total_seconds)}
                    />
                    <SummaryCard
                      icon={<UsersRound className="size-5" aria-hidden="true" />}
                      label="Employees"
                      value={String(teamQuery.data.employee_count)}
                    />
                    <SummaryCard
                      icon={<Clock3 className="size-5" aria-hidden="true" />}
                      label="Open shifts"
                      value={String(teamQuery.data.open_count)}
                    />
                  </div>
                  <div className="flex flex-col gap-2 sm:flex-row">
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => setManualEntryOpen(true)}
                    >
                      <Plus className="size-4" aria-hidden="true" />
                      Add hours
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => exportMutation.mutate()}
                      disabled={exportMutation.isPending || Boolean(invalidRange)}
                    >
                      {exportMutation.isPending ? (
                        <Loader2 className="size-4 animate-spin" aria-hidden="true" />
                      ) : (
                        <Download className="size-4" aria-hidden="true" />
                      )}
                      {exportMutation.isPending ? "Preparing…" : "Export payroll CSV"}
                    </Button>
                  </div>
                </div>
                <AttendanceEntries
                  entries={teamQuery.data.entries}
                  timezone={teamQuery.data.timezone}
                  showEmployee
                  canManage
                  onEdit={setEditingEntry}
                  onVoid={setVoidingEntry}
                />
              </>
            ) : null}
          </TabsContent>
        ) : null}
      </Tabs>

      {manualEntryOpen ? (
        <AttendanceManualEntryDialog
          workspaceId={workspaceId}
          open
          pending={createMutation.isPending}
          onOpenChange={setManualEntryOpen}
          onCreate={(entry) => createMutation.mutate(entry)}
        />
      ) : null}
      {editingEntry ? (
        <AttendanceEntryEditDialog
          entry={editingEntry}
          open
          pending={updateMutation.isPending}
          onOpenChange={(open) => !open && setEditingEntry(null)}
          onSave={(entryId, update) => updateMutation.mutate({ entryId, update })}
        />
      ) : null}
      {voidingEntry ? (
        <AttendanceEntryVoidDialog
          entry={voidingEntry}
          open
          pending={voidMutation.isPending}
          onOpenChange={(open) => !open && setVoidingEntry(null)}
          onConfirm={(entryId, reason) => voidMutation.mutate({ entryId, reason })}
        />
      ) : null}
    </div>
  );
}
