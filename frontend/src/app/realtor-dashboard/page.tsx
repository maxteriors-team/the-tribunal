"use client";

import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Users,
  MessageSquare,
  Reply,
  CalendarCheck,
  Calendar,
  ExternalLink,
  CalendarX,
  type LucideIcon,
} from "lucide-react";

import { AppSidebar } from "@/components/layout/app-sidebar";
import { Card, CardContent } from "@/components/ui/card";
import { PageEmptyState } from "@/components/ui/page-state";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useWorkspaceId } from "@/hooks/use-workspace-id";
import { getRealtorStats, type RealtorStats } from "@/lib/api/realtor";
import { appointmentsApi } from "@/lib/api/appointments";
import { queryKeys } from "@/lib/query-keys";
import type { Appointment } from "@/types";
import { formatDateTime } from "@/lib/utils/date";
import { formatNumber } from "@/lib/utils/number";

// ─── Types ────────────────────────────────────────────────────────────────────

interface MetricCardProps {
  label: string;
  value: number | undefined;
  icon: LucideIcon;
  isPending: boolean;
}

type AppointmentStatus = "scheduled" | "completed" | "cancelled" | "no_show";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function getContactName(appt: Appointment): string {
  if (appt.contact) {
    const { first_name, last_name } = appt.contact;
    return [first_name, last_name].filter(Boolean).join(" ") || "Unknown";
  }
  return "Unknown";
}

function getContactPhone(appt: Appointment): string {
  return appt.contact?.phone_number ?? "—";
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: AppointmentStatus }) {
  switch (status) {
    case "scheduled":
      return (
        <Badge className="bg-yellow-100 text-yellow-800 hover:bg-yellow-100 dark:bg-yellow-900/30 dark:text-yellow-400">
          Pending
        </Badge>
      );
    case "completed":
      return (
        <Badge className="bg-green-100 text-green-800 hover:bg-green-100 dark:bg-green-900/30 dark:text-green-400">
          Confirmed
        </Badge>
      );
    case "cancelled":
      return (
        <Badge className="bg-red-100 text-red-800 hover:bg-red-100 dark:bg-red-900/30 dark:text-red-400">
          Cancelled
        </Badge>
      );
    case "no_show":
      return (
        <Badge className="bg-gray-100 text-gray-700 hover:bg-gray-100 dark:bg-gray-800 dark:text-gray-400">
          No Show
        </Badge>
      );
    default:
      return <Badge variant="secondary">{status}</Badge>;
  }
}

function MetricCard({ label, value, icon: Icon, isPending }: MetricCardProps) {
  return (
    <Card>
      <CardContent className="pt-6">
        <div className="flex items-start justify-between">
          <div className="space-y-1">
            {isPending ? (
              <Skeleton className="h-9 w-16" />
            ) : (
              <p className="text-3xl font-bold tracking-tight">
                {formatNumber(value ?? 0)}
              </p>
            )}
            <p className="text-sm text-muted-foreground">{label}</p>
          </div>
          <div className="rounded-md bg-muted p-2">
            <Icon className="h-5 w-5 text-muted-foreground" />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

function RealtorDashboardContent() {
  const workspaceId = useWorkspaceId();

  // Metrics
  const {
    data: stats,
    isPending: statsLoading,
  } = useQuery<RealtorStats>({
    queryKey: queryKeys.realtor.stats(workspaceId ?? ""),
    queryFn: () => getRealtorStats(workspaceId!),
    enabled: !!workspaceId,
    refetchInterval: 30_000,
  });

  // Upcoming appointments (scheduled + completed, soonest first)
  const {
    data: appointmentsData,
    isPending: appointmentsLoading,
  } = useQuery({
    queryKey: queryKeys.realtor.appointments(workspaceId ?? ""),
    queryFn: () =>
      appointmentsApi.list(workspaceId!, {
        status_filter: "scheduled",
        page_size: 10,
        sort: "asc",
      }),
    enabled: !!workspaceId,
    refetchInterval: 30_000,
  });

  const appointments: Appointment[] = React.useMemo(() => {
    const items = appointmentsData?.items ?? [];
    return [...items].sort(
      (a, b) =>
        new Date(a.scheduled_at).getTime() - new Date(b.scheduled_at).getTime()
    );
  }, [appointmentsData]);

  const metricCards: Array<{
    label: string;
    key: keyof RealtorStats;
    icon: LucideIcon;
  }> = [
    { label: "Leads Uploaded", key: "leads_uploaded", icon: Users },
    { label: "Texts Sent", key: "texts_sent", icon: MessageSquare },
    { label: "Replies Received", key: "replies_received", icon: Reply },
    { label: "Appointments Booked", key: "appointments_booked", icon: CalendarCheck },
  ];

  return (
    <div className="flex flex-col gap-8 p-6 md:p-8 max-w-6xl mx-auto w-full">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          Your Lead Reactivation Dashboard
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Here&apos;s how your campaign is performing
        </p>
      </div>

      {/* Metric Cards */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {metricCards.map(({ label, key, icon }) => (
          <MetricCard
            key={key}
            label={label}
            value={stats?.[key]}
            icon={icon}
            isPending={statsLoading}
          />
        ))}
      </div>

      {/* Upcoming Appointments */}
      <div className="space-y-4">
        <div className="flex items-center gap-2">
          <Calendar className="h-5 w-5 text-muted-foreground" />
          <h2 className="text-lg font-semibold">Upcoming Appointments</h2>
        </div>

        {appointmentsLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-12 w-full" />
            ))}
          </div>
        ) : appointments.length === 0 ? (
          <PageEmptyState
            className="min-h-0 rounded-lg border border-dashed py-16"
            title="No upcoming appointments yet"
            description="Your AI agent is working on it!"
            icon={<CalendarX className="h-10 w-10" />}
          />
        ) : (
          <div className="rounded-lg border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Lead Name</TableHead>
                  <TableHead>Phone</TableHead>
                  <TableHead>Date &amp; Time</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="w-16 text-right">Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {appointments.map((appt) => {
                  const bookingUrl = appt.calcom_booking_uid
                    ? `https://cal.com/booking/${appt.calcom_booking_uid}`
                    : null;

                  return (
                    <TableRow key={appt.id}>
                      <TableCell className="font-medium">
                        {getContactName(appt)}
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {getContactPhone(appt)}
                      </TableCell>
                      <TableCell>{formatDateTime(appt.scheduled_at)}</TableCell>
                      <TableCell>
                        <StatusBadge status={appt.status as AppointmentStatus} />
                      </TableCell>
                      <TableCell className="text-right">
                        {bookingUrl ? (
                          <Button
                            variant="ghost"
                            size="icon"
                            asChild
                            className="h-8 w-8"
                          >
                            <a
                              href={bookingUrl}
                              target="_blank"
                              rel="noopener noreferrer"
                              aria-label="Open Cal.com booking"
                            >
                              <ExternalLink className="h-4 w-4" />
                            </a>
                          </Button>
                        ) : (
                          <span className="text-muted-foreground/40">—</span>
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        )}
      </div>
    </div>
  );
}

export default function RealtorDashboardPage() {
  return (
    <AppSidebar>
      <RealtorDashboardContent />
    </AppSidebar>
  );
}
