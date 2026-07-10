"use client";

import {
  ChevronLeft,
  ChevronRight,
  Plus,
  Calendar as CalendarIcon,
  Settings,
} from "lucide-react";
import { motion } from "motion/react";
import Link from "next/link";
import { useState, useMemo } from "react";
import { toast } from "sonner";

import { ReminderBadges } from "@/components/calendar/appointment-actions";
import { AppointmentDetailsDialog } from "@/components/calendar/appointment-details-dialog";
import { CalendarMonthView } from "@/components/calendar/calendar-month-view";
import { NewAppointmentDialog } from "@/components/calendar/new-appointment-dialog";
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
import {
  PageErrorState,
  PageLoadingState,
} from "@/components/ui/page-state";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useAppointments, useDeleteAppointment } from "@/hooks/useAppointments";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import {
  STATUS_OPTIONS,
  appointmentsForDay,
  buildAppointmentsQueryParams,
  getContactName,
  getInitials,
  getMonthRange,
  getWeekRange,
  scheduledCount,
  statusFilterLabel,
  todaysAppointments,
  upcomingAppointments,
  type StatusFilter,
} from "@/lib/calendar/calendar-derivations";
import { appointmentStatusColors } from "@/lib/status-colors";
import { formatDate, addDays, addMonths, isSameDay } from "@/lib/utils/date";

type CalendarView = "month" | "week";

export function CalendarPage() {
  const [currentDate, setCurrentDate] = useState(new Date());
  const [view, setView] = useState<CalendarView>("month");
  const [selectedAppointmentId, setSelectedAppointmentId] = useState<number | null>(null);
  const [isScheduleOpen, setIsScheduleOpen] = useState(false);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("");
  const workspaceId = useWorkspaceId();

  // The visible date range drives both the fetch (query key + params) and the
  // grid. Month view spans whole weeks around the month; week view is Mon→Sun.
  const monthRange = useMemo(() => getMonthRange(currentDate), [currentDate]);
  const weekRange = useMemo(() => getWeekRange(currentDate), [currentDate]);
  const rangeStartIso =
    view === "month" ? monthRange.gridStartIso : weekRange.weekStartIso;
  const rangeEndIso =
    view === "month" ? monthRange.gridEndIso : weekRange.weekEndIso;

  const queryParams = useMemo(
    () => buildAppointmentsQueryParams(rangeStartIso, rangeEndIso, statusFilter),
    [rangeStartIso, rangeEndIso, statusFilter],
  );

  const { data: appointmentsData, isPending, error, refetch } = useAppointments(
    workspaceId ?? "",
    queryParams,
  );
  const deleteAppointmentMutation = useDeleteAppointment(workspaceId ?? "");

  const appointmentsList = useMemo(
    () => appointmentsData?.items || [],
    [appointmentsData?.items],
  );

  const totalCount = appointmentsData?.total ?? 0;

  const selectedAppointment = useMemo(
    () => appointmentsList.find((apt) => apt.id === selectedAppointmentId) ?? null,
    [appointmentsList, selectedAppointmentId],
  );

  const todayAppointments = useMemo(
    () => todaysAppointments(appointmentsList),
    [appointmentsList],
  );

  const upcomingList = useMemo(
    () => upcomingAppointments(appointmentsList),
    [appointmentsList],
  );

  const goToday = () => setCurrentDate(new Date());
  const goPrev = () =>
    setCurrentDate((d) => (view === "month" ? addMonths(d, -1) : addDays(d, -7)));
  const goNext = () =>
    setCurrentDate((d) => (view === "month" ? addMonths(d, 1) : addDays(d, 7)));

  const handleDeleteAppointment = async (appointmentId: number) => {
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

  if (isPending) {
    return <PageLoadingState className="h-96" message="Loading appointments…" />;
  }

  if (error) {
    return (
      <PageErrorState
        className="h-96"
        message="Failed to load appointments"
        onRetry={() => refetch()}
      />
    );
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Calendar</h1>
          <p className="text-muted-foreground">
            Manage appointments and scheduling
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" asChild>
            <Link href="/settings">
              <Settings className="mr-2 size-4" />
              Settings
            </Link>
          </Button>
          <Button onClick={() => setIsScheduleOpen(true)}>
            <Plus className="mr-2 size-4" />
            New Appointment
          </Button>
        </div>
      </div>

      <NewAppointmentDialog
        open={isScheduleOpen}
        onOpenChange={setIsScheduleOpen}
      />

      {/* Filter Bar */}
      <div className="flex items-center gap-2">
        <div className="flex items-center gap-1 bg-muted rounded-lg p-1">
          {STATUS_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => setStatusFilter(opt.value as StatusFilter)}
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
          {totalCount} result{totalCount !== 1 ? "s" : ""}
        </span>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Calendar View */}
        <div className="lg:col-span-2 space-y-4">
          <Card>
            <CardHeader className="pb-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <CardTitle className="text-lg">
                  {formatDate(currentDate, { pattern: "MMMM yyyy" })}
                </CardTitle>
                <div className="flex items-center gap-2">
                  {/* View toggle */}
                  <div className="flex items-center gap-1 bg-muted rounded-lg p-1">
                    {(["month", "week"] as const).map((v) => (
                      <button
                        key={v}
                        onClick={() => setView(v)}
                        className={`px-3 py-1 rounded-md text-sm font-medium capitalize transition-colors ${
                          view === v
                            ? "bg-background shadow-sm text-foreground"
                            : "text-muted-foreground hover:text-foreground"
                        }`}
                      >
                        {v}
                      </button>
                    ))}
                  </div>
                  {/* Navigation */}
                  <div className="flex items-center gap-1">
                    <Button variant="outline" size="icon-sm" onClick={goPrev}>
                      <ChevronLeft className="size-4" />
                    </Button>
                    <Button variant="outline" size="sm" onClick={goToday}>
                      Today
                    </Button>
                    <Button variant="outline" size="icon-sm" onClick={goNext}>
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
                  appointments={appointmentsList}
                  onSelect={(apt) => setSelectedAppointmentId(apt.id)}
                />
              ) : (
                <>
                  {/* Week Days Header */}
                  <div className="grid grid-cols-7 gap-2 mb-2">
                    {weekRange.weekDays.map((day) => (
                      <div
                        key={day.toISOString()}
                        className={`text-center p-2 rounded-lg ${
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

                  {/* Appointments for the week */}
                  <div className="grid grid-cols-7 gap-2 min-h-[300px]">
                    {weekRange.weekDays.map((day) => {
                      const dayAppointments = appointmentsForDay(
                        appointmentsList,
                        day,
                      );

                      return (
                        <div
                          key={day.toISOString()}
                          className="border rounded-lg p-2 min-h-[200px]"
                        >
                          <ScrollArea className="h-[180px]">
                            <div className="space-y-1">
                              {dayAppointments.map((apt) => (
                                <motion.button
                                  key={apt.id}
                                  className="w-full text-left p-2 rounded-md bg-primary/10 hover:bg-primary/20 transition-colors"
                                  whileHover={{ scale: 1.02 }}
                                  whileTap={{ scale: 0.98 }}
                                  onClick={() => setSelectedAppointmentId(apt.id)}
                                >
                                  <p className="text-xs font-medium truncate">
                                    {apt.service_type || "Appointment"}
                                  </p>
                                  <p className="text-xs text-muted-foreground">
                                    {formatDate(apt.scheduled_at, {
                                      pattern: "h:mm a",
                                    })}
                                  </p>
                                </motion.button>
                              ))}
                            </div>
                          </ScrollArea>
                        </div>
                      );
                    })}
                  </div>
                </>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Sidebar */}
        <div className="space-y-4">
          {/* Today's Schedule */}
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
              {todayAppointments.length === 0 ? (
                <p className="text-sm text-muted-foreground text-center py-4">
                  No appointments today
                </p>
              ) : (
                <div className="space-y-3">
                  {todayAppointments.map((apt) => (
                    <div
                      key={apt.id}
                      role="button"
                      tabIndex={0}
                      className="flex items-center gap-3 p-2 rounded-lg border hover:bg-muted/50 transition-colors cursor-pointer"
                      onClick={() => setSelectedAppointmentId(apt.id)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          setSelectedAppointmentId(apt.id);
                        }
                      }}
                    >
                      <Avatar className="size-8">
                        <AvatarFallback className="text-xs">
                          {getInitials(
                            apt.contact?.first_name || "",
                            apt.contact?.last_name,
                          )}
                        </AvatarFallback>
                      </Avatar>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium truncate">
                          {getContactName(apt.contact)}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          {formatDate(apt.scheduled_at, { pattern: "h:mm a" })} •{" "}
                          {apt.duration_minutes}min
                        </p>
                      </div>
                      <ReminderBadges
                        reminderSentAt={apt.reminder_sent_at}
                        remindersSent={apt.reminders_sent}
                      />
                      <Badge
                        variant="outline"
                        className={appointmentStatusColors[apt.status]}
                      >
                        {apt.status}
                      </Badge>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Upcoming */}
          <Card>
            <CardHeader>
              <CardTitle>Upcoming</CardTitle>
              <CardDescription>Next in view</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="space-y-3">
                {upcomingList.slice(0, 5).map((apt) => (
                  <div
                    key={apt.id}
                    role="button"
                    tabIndex={0}
                    className="flex items-center gap-3 p-2 rounded-lg hover:bg-muted/50 transition-colors cursor-pointer"
                    onClick={() => setSelectedAppointmentId(apt.id)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        setSelectedAppointmentId(apt.id);
                      }
                    }}
                  >
                    <div className="text-center min-w-[40px]">
                      <div className="text-xs font-medium text-muted-foreground">
                        {formatDate(apt.scheduled_at, { pattern: "MMM" })}
                      </div>
                      <div className="text-lg font-bold">
                        {formatDate(apt.scheduled_at, { pattern: "d" })}
                      </div>
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">
                        {getContactName(apt.contact)}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {apt.service_type || "Appointment"} •{" "}
                        {formatDate(apt.scheduled_at, { pattern: "h:mm a" })}
                      </p>
                    </div>
                    <Badge
                      variant="outline"
                      className={appointmentStatusColors[apt.status]}
                    >
                      {apt.status}
                    </Badge>
                  </div>
                ))}
                {upcomingList.length === 0 && (
                  <p className="text-sm text-muted-foreground text-center py-4">
                    Nothing upcoming in this range
                  </p>
                )}
              </div>
            </CardContent>
          </Card>

          {/* Quick Stats */}
          <Card>
            <CardHeader>
              <CardTitle>{view === "month" ? "This Month" : "This Week"}</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 gap-4 text-center">
                <div className="p-3 rounded-lg bg-muted/50">
                  <div className="text-2xl font-bold">{totalCount}</div>
                  <div className="text-xs text-muted-foreground">
                    {statusFilterLabel(statusFilter)}
                  </div>
                </div>
                <div className="p-3 rounded-lg bg-muted/50">
                  <div className="text-2xl font-bold text-success">
                    {scheduledCount(appointmentsList)}
                  </div>
                  <div className="text-xs text-muted-foreground">Scheduled</div>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Shared appointment details dialog (week + month + sidebar) */}
      <AppointmentDetailsDialog
        appointment={selectedAppointment}
        workspaceId={workspaceId ?? undefined}
        open={selectedAppointmentId !== null}
        onOpenChange={(open) => !open && setSelectedAppointmentId(null)}
        onDelete={handleDeleteAppointment}
        onChanged={() => void refetch()}
        deleting={deleteAppointmentMutation.isPending}
      />
    </div>
  );
}
