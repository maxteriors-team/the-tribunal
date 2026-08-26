"use client";

import { useQuery } from "@tanstack/react-query";
import { BriefcaseBusiness, CalendarCheck, Send } from "lucide-react";
import { useState } from "react";

import { ReportDateRangePicker } from "@/components/reports/report-date-range-picker";
import { currentMonthRange, type DateRange } from "@/components/reports/sales-performance-metrics";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { reportingApi } from "@/lib/api/reporting";
import { queryKeys } from "@/lib/query-keys";

interface CalendarStatisticsProps {
  workspaceId: string;
}

const statistics = [
  { key: "appointments_booked", label: "Booked discovery calls", icon: CalendarCheck },
  { key: "quotes_issued", label: "Quotes sent", icon: Send },
  { key: "jobs_completed", label: "Jobs completed", icon: BriefcaseBusiness },
] as const;

export function CalendarStatistics({ workspaceId }: CalendarStatisticsProps) {
  const [range, setRange] = useState<DateRange>(() => currentMonthRange());
  const dateFrom = range.from;
  const dateTo = range.to;
  const reportQuery = useQuery({
    queryKey: queryKeys.reports.salesPerformance(workspaceId, {
      date_from: dateFrom,
      date_to: dateTo,
    }),
    queryFn: () =>
      reportingApi.salesPerformance(workspaceId, { date_from: dateFrom, date_to: dateTo }),
  });

  return (
    <section aria-labelledby="calendar-statistics-title" className="space-y-3">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 id="calendar-statistics-title" className="text-lg font-semibold">
            Statistics
          </h2>
          <p className="text-sm text-muted-foreground">Activity inside the selected date range.</p>
        </div>
        <ReportDateRangePicker value={range} onChange={setRange} />
      </div>

      {reportQuery.isError ? (
        <div className="flex items-center justify-between gap-3 rounded-md border border-destructive/30 p-3 text-sm">
          <span>Statistics could not be loaded.</span>
          <Button variant="outline" size="sm" onClick={() => reportQuery.refetch()}>
            Retry
          </Button>
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-3">
          {statistics.map(({ key, label, icon: Icon }) => (
            <Card key={key}>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">{label}</CardTitle>
                <Icon className="size-4 text-muted-foreground" aria-hidden="true" />
              </CardHeader>
              <CardContent>
                <p
                  className="text-2xl font-bold"
                  aria-label={`${label}: ${reportQuery.data?.[key] ?? 0}`}
                >
                  {reportQuery.isPending ? "—" : (reportQuery.data?.[key] ?? 0)}
                </p>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </section>
  );
}
