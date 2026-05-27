"use client";

import {
  ChevronLeft,
  ChevronRight,
  Plus,
  Calendar as CalendarIcon,
  Clock,
  Settings,
  Loader2,
  AlertCircle,
  Trash2,
  RefreshCw,
  Bell,
} from "lucide-react";
import { motion } from "motion/react";
import Link from "next/link";
import { useState, useMemo } from "react";
import { toast } from "sonner";

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
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useAppointments, useDeleteAppointment } from "@/hooks/useAppointments";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { appointmentsApi } from "@/lib/api/appointments";
import { appointmentStatusColors } from "@/lib/status-colors";
import { formatDate, addDays, startOfWeek, endOfWeek, isSameDay } from "@/lib/utils/date";
import type { Appointment, Contact } from "@/types";

// Status filter options
const STATUS_OPTIONS = [
  { value: "", label: "All" },
  { value: "scheduled", label: "Scheduled" },
  { value: "no_show", label: "No-Show" },
  { value: "completed", label: "Completed" },
  { value: "cancelled", label: "Cancelled" },
] as const;

type StatusFilter = "" | "scheduled" | "no_show" | "completed" | "cancelled";

// Helper to get contact initials
function getInitials(firstName: string, lastName?: string): string {
  const first = firstName?.[0] ?? "";
  const last = lastName?.[0] ?? "";
  return (first + last).toUpperCase() || "?";
}

// Helper to get contact display name
function getContactName(contact: Contact | null | undefined): string {
  if (!contact) return "Unknown";
  return [contact.first_name, contact.last_name].filter(Boolean).join(" ");
}

// Helper to convert minutes offset to human-readable label
function offsetToLabel(minutes: number): string {
  if (minutes >= 1440 && minutes % 1440 === 0) return `${minutes / 1440}d`;
  if (minutes >= 60 && minutes % 60 === 0) return `${minutes / 60}h`;
  return `${minutes}m`;
}

interface ReminderBadgesProps {
  reminderSentAt?: string | null;
  remindersSent?: number[] | null;
  reminderOffsets?: number[] | null;
}

function ReminderBadges({ reminderSentAt, remindersSent, reminderOffsets }: ReminderBadgesProps) {
  const sent = remindersSent ?? [];

  // If we have reminder offsets (from agent data on appointment), show multi-badge
  if (reminderOffsets && reminderOffsets.length > 0) {
    return (
      <div className="flex flex-wrap gap-1">
        {reminderOffsets.map((offset) => {
          const fired = sent.includes(offset);
          return (
            <Badge
              key={offset}
              variant="outline"
              className={fired
                ? "text-success border-success/20 text-[10px] py-0"
                : "text-muted-foreground border-muted text-[10px] py-0"
              }
            >
              {offsetToLabel(offset)}{fired ? " ✓" : ""}
            </Badge>
          );
        })}
      </div>
    );
  }

  // If we have fired reminders but no offset config, show fired ones
  if (sent.length > 0) {
    return (
      <div className="flex flex-wrap gap-1">
        {sent.map((offset) => (
          <Badge
            key={offset}
            variant="outline"
            className="text-success border-success/20 text-[10px] py-0"
          >
            {offsetToLabel(offset)} ✓
          </Badge>
        ))}
      </div>
    );
  }

  // Legacy fallback: just reminder_sent_at set
  if (reminderSentAt) {
    return (
      <Badge variant="outline" className="text-success border-success/20 text-[10px] py-0">
        Reminder sent
      </Badge>
    );
  }

  return null;
}

interface SyncButtonProps {
  appointment: Appointment;
  workspaceId: string;
  onSynced: () => void;
}

function SyncButton({ appointment, workspaceId, onSynced }: SyncButtonProps) {
  const [isSyncing, setIsSyncing] = useState(false);

  if (appointment.sync_status !== "pending") return null;

  const handleSync = async (e: React.MouseEvent) => {
    e.stopPropagation();
    setIsSyncing(true);
    try {
      const result = await appointmentsApi.syncAppointment(workspaceId, appointment.id);
      if (result.status === "synced") {
        toast.success("Synced to Cal.com");
        onSynced();
      } else {
        toast.error(`Sync failed: ${result.error ?? "Unknown error"}`);
      }
    } catch {
      toast.error("Failed to sync appointment");
    } finally {
      setIsSyncing(false);
    }
  };

  return (
    <Button
      variant="outline"
      size="sm"
      className="text-xs h-7 gap-1"
      onClick={handleSync}
      disabled={isSyncing}
      title="Sync to Cal.com"
    >
      {isSyncing ? (
        <Loader2 className="size-3 animate-spin" />
      ) : (
        <RefreshCw className="size-3" />
      )}
      Sync
    </Button>
  );
}

interface SendReminderButtonProps {
  appointment: Appointment;
  workspaceId: string;
  onSent: () => void;
}

function SendReminderButton({ appointment, workspaceId, onSent }: SendReminderButtonProps) {
  const [isSending, setIsSending] = useState(false);

  if (appointment.status !== "scheduled") return null;

  const handleSend = async (e: React.MouseEvent) => {
    e.stopPropagation();
    setIsSending(true);
    try {
      const result = await appointmentsApi.sendReminder(workspaceId, appointment.id);
      if (result.success) {
        toast.success(`Reminder sent to ${result.sent_to ?? "contact"}`);
        onSent();
      } else {
        toast.error(result.message || "Failed to send reminder");
      }
    } catch {
      toast.error("Failed to send reminder");
    } finally {
      setIsSending(false);
    }
  };

  return (
    <Button
      variant="outline"
      size="sm"
      className="text-xs h-7 gap-1"
      onClick={handleSend}
      disabled={isSending}
      title="Send SMS reminder"
    >
      {isSending ? (
        <Loader2 className="size-3 animate-spin" />
      ) : (
        <Bell className="size-3" />
      )}
      Remind
    </Button>
  );
}

export function CalendarPage() {
  const [currentDate, setCurrentDate] = useState(new Date());
  const [selectedAppointmentId, setSelectedAppointmentId] = useState<number | null>(null);
  const [isScheduleOpen, setIsScheduleOpen] = useState(false);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("");
  const workspaceId = useWorkspaceId();

  // Compute week bounds before the data fetch so they drive the query key + params
  const weekStart = startOfWeek(currentDate, { weekStartsOn: 1 });
  const weekEnd = endOfWeek(currentDate, { weekStartsOn: 1 });
  const weekStartIso = weekStart.toISOString();
  const weekEndIso = weekEnd.toISOString();
  const weekDays = Array.from({ length: 7 }, (_, i) => addDays(weekStart, i));

  const queryParams = {
    page: 1,
    page_size: 100,
    date_from: weekStartIso,
    date_to: weekEndIso,
    ...(statusFilter ? { status_filter: statusFilter } : {}),
  };

  const { data: appointmentsData, isPending, error, refetch } = useAppointments(
    workspaceId ?? "",
    queryParams
  );
  const deleteAppointmentMutation = useDeleteAppointment(workspaceId ?? "");

  const appointmentsList = useMemo(
    () => appointmentsData?.items || [],
    [appointmentsData?.items]
  );

  const totalCount = appointmentsData?.total ?? 0;

  const todayAppointments = useMemo(
    () =>
      appointmentsList.filter((apt) =>
        isSameDay(new Date(apt.scheduled_at), new Date())
      ),
    [appointmentsList]
  );

  const upcomingAppointments = useMemo(
    () =>
      appointmentsList.filter(
        (apt) => new Date(apt.scheduled_at) > new Date()
      ),
    [appointmentsList]
  );

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
    return (
      <div className="p-6 flex items-center justify-center h-96">
        <Loader2 className="size-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 flex flex-col items-center justify-center h-96 gap-2">
        <AlertCircle className="size-8 text-destructive" />
        <p className="text-muted-foreground">Failed to load appointments</p>
      </div>
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
              Cal.com Settings
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
          {/* Week Navigation */}
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
                    onClick={() => setCurrentDate(addDays(currentDate, -7))}
                  >
                    <ChevronLeft className="size-4" />
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setCurrentDate(new Date())}
                  >
                    Today
                  </Button>
                  <Button
                    variant="outline"
                    size="icon-sm"
                    onClick={() => setCurrentDate(addDays(currentDate, 7))}
                  >
                    <ChevronRight className="size-4" />
                  </Button>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              {/* Week Days Header */}
              <div className="grid grid-cols-7 gap-2 mb-2">
                {weekDays.map((day) => (
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
                    <div className="text-lg font-bold">{formatDate(day, { pattern: "d" })}</div>
                  </div>
                ))}
              </div>

              {/* Appointments for the week */}
              <div className="grid grid-cols-7 gap-2 min-h-[300px]">
                {weekDays.map((day) => {
                  const dayAppointments = appointmentsList.filter((apt) =>
                    isSameDay(new Date(apt.scheduled_at), day)
                  );

                  return (
                    <div
                      key={day.toISOString()}
                      className="border rounded-lg p-2 min-h-[200px]"
                    >
                      <ScrollArea className="h-[180px]">
                        <div className="space-y-1">
                          {dayAppointments.map((apt) => (
                            <Dialog key={apt.id} open={selectedAppointmentId === apt.id} onOpenChange={(open) => !open && setSelectedAppointmentId(null)}>
                              <DialogTrigger asChild>
                                <motion.button
                                  className="w-full text-left p-2 rounded-md bg-primary/10 hover:bg-primary/20 transition-colors"
                                  whileHover={{ scale: 1.02 }}
                                  whileTap={{ scale: 0.98 }}
                                  onClick={() => setSelectedAppointmentId(apt.id)}
                                >
                                  <p className="text-xs font-medium truncate">
                                    {apt.service_type || "Appointment"}
                                  </p>
                                  <p className="text-xs text-muted-foreground">
                                    {formatDate(apt.scheduled_at, { pattern: "h:mm a" })}
                                  </p>
                                  {apt.sync_status === "pending" && (
                                    <Badge variant="outline" className="text-warning border-warning/20 text-[10px] py-0 mt-0.5">
                                      pending sync
                                    </Badge>
                                  )}
                                </motion.button>
                              </DialogTrigger>
                              <DialogContent>
                                <DialogHeader>
                                  <DialogTitle>{apt.service_type || "Appointment"}</DialogTitle>
                                  <DialogDescription>
                                    {formatDate(apt.scheduled_at, {
                                      pattern: "EEEE, MMMM d, yyyy 'at' h:mm a",
                                    })}
                                  </DialogDescription>
                                </DialogHeader>
                                <div className="space-y-4 py-4">
                                  <div className="flex items-start justify-between gap-3">
                                    <div className="flex items-center gap-3">
                                      <Avatar className="size-10">
                                        <AvatarFallback>
                                          {getInitials(apt.contact?.first_name || "", apt.contact?.last_name)}
                                        </AvatarFallback>
                                      </Avatar>
                                      <div>
                                        <p className="font-medium">
                                          {getContactName(apt.contact)}
                                        </p>
                                        <Badge
                                          variant="outline"
                                          className={appointmentStatusColors[apt.status]}
                                        >
                                          {apt.status}
                                        </Badge>
                                        <ReminderBadges
                                          reminderSentAt={apt.reminder_sent_at}
                                          remindersSent={apt.reminders_sent}
                                        />
                                        {apt.reminder_sent_at && (
                                          <p className="text-xs text-muted-foreground">
                                            Last reminder: {formatDate(apt.reminder_sent_at, { pattern: "MMM d, h:mm a" })}
                                          </p>
                                        )}
                                      </div>
                                    </div>
                                    <div className="flex items-center gap-2">
                                      {workspaceId && (
                                        <SyncButton
                                          appointment={apt}
                                          workspaceId={workspaceId}
                                          onSynced={() => void refetch()}
                                        />
                                      )}
                                      {workspaceId && apt.status === "scheduled" && (
                                        <SendReminderButton
                                          appointment={apt}
                                          workspaceId={workspaceId}
                                          onSent={() => void refetch()}
                                        />
                                      )}
                                      {apt.status === "scheduled" && (
                                        <Button
                                          variant="ghost"
                                          size="icon"
                                          onClick={() => handleDeleteAppointment(apt.id)}
                                          disabled={deleteAppointmentMutation.isPending}
                                          className="text-destructive hover:text-destructive"
                                          aria-label="Delete appointment"
                                        >
                                          <Trash2 className="size-4" />
                                        </Button>
                                      )}
                                    </div>
                                  </div>
                                  <div className="grid gap-2 text-sm">
                                    <div className="flex items-center gap-2">
                                      <Clock className="size-4 text-muted-foreground" />
                                      <span>{apt.duration_minutes} minutes</span>
                                    </div>
                                    {apt.sync_status === "pending" && (
                                      <div className="flex items-center gap-2 text-warning">
                                        <span className="text-xs">Not synced to Cal.com</span>
                                      </div>
                                    )}
                                    {apt.sync_status === "synced" && apt.calcom_booking_uid && (
                                      <div className="text-xs text-muted-foreground">
                                        Cal.com UID: {apt.calcom_booking_uid}
                                      </div>
                                    )}
                                    {apt.sync_error && (
                                      <div className="text-xs text-destructive">
                                        Sync error: {apt.sync_error}
                                      </div>
                                    )}
                                    {apt.notes && (
                                      <div className="text-sm text-muted-foreground">
                                        {apt.notes}
                                      </div>
                                    )}
                                  </div>
                                </div>
                              </DialogContent>
                            </Dialog>
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
                          {getInitials(apt.contact?.first_name || "", apt.contact?.last_name)}
                        </AvatarFallback>
                      </Avatar>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium truncate">
                          {getContactName(apt.contact)}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          {formatDate(apt.scheduled_at, { pattern: "h:mm a" })} • {apt.duration_minutes}min
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
              <CardDescription>Next 7 days</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="space-y-3">
                {upcomingAppointments.slice(0, 5).map((apt) => (
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
                        {apt.service_type || "Appointment"} • {formatDate(apt.scheduled_at, { pattern: "h:mm a" })}
                      </p>
                    </div>
                    {apt.sync_status === "pending" && (
                      <Badge variant="outline" className="text-warning border-warning/20 text-[10px] py-0 shrink-0">
                        sync
                      </Badge>
                    )}
                    <Badge
                      variant="outline"
                      className={appointmentStatusColors[apt.status]}
                    >
                      {apt.status}
                    </Badge>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          {/* Quick Stats */}
          <Card>
            <CardHeader>
              <CardTitle>This Week</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 gap-4 text-center">
                <div className="p-3 rounded-lg bg-muted/50">
                  <div className="text-2xl font-bold">
                    {totalCount}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {statusFilter
                      ? STATUS_OPTIONS.find((o) => o.value === statusFilter)?.label ?? "Filtered"
                      : "Total"}
                  </div>
                </div>
                <div className="p-3 rounded-lg bg-muted/50">
                  <div className="text-2xl font-bold text-success">
                    {appointmentsList.filter((a) => a.status === "scheduled").length}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    Scheduled
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
