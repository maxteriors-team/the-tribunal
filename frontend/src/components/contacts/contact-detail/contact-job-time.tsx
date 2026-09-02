"use client";

import { Clock3 } from "lucide-react";

import { PageErrorState, PageLoadingState } from "@/components/ui/page-state";
import { useContactJobTime } from "@/hooks/useContactJobTime";
import { formatDate } from "@/lib/utils/date";

interface ContactJobTimeProps {
  workspaceId: string;
  contactId: number;
}

function formatHours(hours: number): string {
  if (hours < 1) return `${Math.round(hours * 60)}m`;
  return `${hours.toFixed(hours >= 10 ? 1 : 2)}h`;
}

export function ContactJobTime({ workspaceId, contactId }: ContactJobTimeProps) {
  const { data, isPending, isError, refetch } = useContactJobTime(workspaceId, contactId);

  return (
    <section className="space-y-2" aria-labelledby="client-job-time-heading">
      <div className="flex items-center justify-between gap-2 px-2">
        <h3 id="client-job-time-heading" className="text-sm font-medium text-muted-foreground">
          Job time
        </h3>
        {data && data.entry_count > 0 ? (
          <span className="text-sm font-semibold tabular-nums">
            {formatHours(data.total_hours)}
          </span>
        ) : null}
      </div>

      {isPending ? (
        <PageLoadingState className="min-h-24" />
      ) : isError || !data ? (
        <PageErrorState
          className="min-h-24"
          message="Couldn't load job time."
          onRetry={() => {
            void refetch();
          }}
        />
      ) : data.entries.length === 0 ? (
        <div className="rounded-lg bg-muted/40 px-3 py-4 text-sm text-muted-foreground">
          No job time recorded yet.
        </div>
      ) : (
        <ul className="max-h-72 divide-y divide-border/40 overflow-y-auto rounded-lg bg-muted/40 px-2">
          {data.entries.map((entry) => (
            <li key={entry.id} className="flex items-start gap-2 py-2 text-xs">
              <Clock3 className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate font-medium">{entry.job_title}</span>
                  <span className="shrink-0 tabular-nums">
                    {entry.ended_at ? formatHours(entry.duration_hours) : "Running"}
                  </span>
                </div>
                <div className="mt-0.5 truncate text-muted-foreground">
                  {entry.technician_name ?? "Technician"} ·{" "}
                  {formatDate(entry.started_at, { pattern: "MMM d, yyyy" })}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
