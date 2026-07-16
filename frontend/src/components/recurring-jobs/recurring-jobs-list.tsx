"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  MoreHorizontal,
  Pencil,
  Play,
  Plus,
  Repeat,
  Trash2,
} from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  PageEmptyState,
  PageErrorState,
  PageLoadingState,
} from "@/components/ui/page-state";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { contactsApi } from "@/lib/api/contacts";
import { recurringJobsApi } from "@/lib/api/recurring-jobs";
import { queryKeys } from "@/lib/query-keys";
import { POLL_60S } from "@/lib/query-options";
import { formatDate } from "@/lib/utils/date";
import { getApiErrorMessage } from "@/lib/utils/errors";
import type { RecurringJobTemplate } from "@/types";

import { RecurringJobDialog } from "./recurring-job-dialog";

const FREQUENCY_LABELS: Record<RecurringJobTemplate["frequency"], string> = {
  weekly: "Weekly",
  biweekly: "Every 2 weeks",
  monthly: "Monthly",
  quarterly: "Quarterly",
  yearly: "Yearly",
};

function scheduleLabel(t: RecurringJobTemplate): string {
  const base = FREQUENCY_LABELS[t.frequency];
  if (t.interval <= 1) return base;
  return `${base} × ${t.interval}`;
}

export function RecurringJobsList() {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<RecurringJobTemplate | null>(null);

  const query = useQuery({
    queryKey: queryKeys.recurringJobs.list(workspaceId ?? ""),
    queryFn: () => recurringJobsApi.list(workspaceId ?? ""),
    enabled: Boolean(workspaceId),
    ...POLL_60S,
  });

  const contactsQuery = useQuery({
    queryKey: queryKeys.contacts.allRecords(workspaceId ?? ""),
    queryFn: () => contactsApi.listAll(workspaceId ?? ""),
    enabled: Boolean(workspaceId),
  });

  const contactName = (id: number): string => {
    const c = contactsQuery.data?.find((x) => x.id === id);
    if (!c) return `Customer #${id}`;
    const name = [c.first_name, c.last_name].filter(Boolean).join(" ").trim();
    return name || c.email || `Customer #${id}`;
  };

  const invalidate = () => {
    if (!workspaceId) return;
    void queryClient.invalidateQueries({
      queryKey: queryKeys.recurringJobs.all(workspaceId),
    });
  };

  const runMutation = useMutation({
    mutationFn: (id: string) => recurringJobsApi.run(workspaceId ?? "", id),
    onSuccess: (result) => {
      toast.success(
        result.created > 0
          ? `Generated ${result.created} job${result.created > 1 ? "s" : ""}`
          : "Nothing due — cursor advanced"
      );
      invalidate();
      if (workspaceId) {
        void queryClient.invalidateQueries({
          queryKey: queryKeys.jobs.all(workspaceId),
        });
      }
    },
    onError: (err: unknown) =>
      toast.error(getApiErrorMessage(err, "Failed to generate job")),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => recurringJobsApi.delete(workspaceId ?? "", id),
    onSuccess: () => {
      toast.success("Recurring job deleted");
      invalidate();
    },
    onError: (err: unknown) =>
      toast.error(getApiErrorMessage(err, "Failed to delete")),
  });

  const openCreate = () => {
    setEditing(null);
    setDialogOpen(true);
  };
  const openEdit = (t: RecurringJobTemplate) => {
    setEditing(t);
    setDialogOpen(true);
  };

  const newButton = (
    <Button onClick={openCreate} size="sm">
      <Plus className="mr-1.5 h-4 w-4" />
      New recurring job
    </Button>
  );

  const busy = runMutation.isPending || deleteMutation.isPending;

  let body: React.ReactNode;
  if (!workspaceId || query.isLoading) {
    body = <PageLoadingState message="Loading recurring jobs..." />;
  } else if (query.isError) {
    body = (
      <PageErrorState
        message={getApiErrorMessage(query.error, "Failed to load recurring jobs")}
        onRetry={() => void query.refetch()}
      />
    );
  } else {
    const items = query.data?.items ?? [];
    if (items.length === 0) {
      body = (
        <PageEmptyState
          icon={<Repeat className="size-8" />}
          title="No recurring jobs yet"
          description="Set up a maintenance contract and a job auto-generates on schedule."
          action={newButton}
        />
      );
    } else {
      body = (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Job</TableHead>
              <TableHead>Schedule</TableHead>
              <TableHead>Next occurrence</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="w-10" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((t) => (
              <TableRow key={t.id} className={t.is_active ? "" : "opacity-50"}>
                <TableCell className="font-medium">
                  {t.title}
                  <div className="text-xs text-muted-foreground">
                    {contactName(t.contact_id)}
                  </div>
                </TableCell>
                <TableCell>
                  <Badge variant="secondary">{scheduleLabel(t)}</Badge>
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {formatDate(t.next_run_at, { pattern: "MMM d, yyyy · h:mm a" })}
                </TableCell>
                <TableCell>
                  {t.is_active ? (
                    <Badge>Active</Badge>
                  ) : (
                    <Badge variant="outline">Paused</Badge>
                  )}
                </TableCell>
                <TableCell>
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button
                        variant="ghost"
                        size="icon"
                        disabled={busy}
                        aria-label="Actions"
                      >
                        <MoreHorizontal className="h-4 w-4" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuItem onClick={() => runMutation.mutate(t.id)}>
                        <Play className="mr-2 h-4 w-4" />
                        Generate next now
                      </DropdownMenuItem>
                      <DropdownMenuItem onClick={() => openEdit(t)}>
                        <Pencil className="mr-2 h-4 w-4" />
                        Edit
                      </DropdownMenuItem>
                      <DropdownMenuItem
                        variant="destructive"
                        onClick={() => deleteMutation.mutate(t.id)}
                      >
                        <Trash2 className="mr-2 h-4 w-4" />
                        Delete
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      );
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-end">{newButton}</div>
      {body}
      <RecurringJobDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        template={editing}
      />
    </div>
  );
}
