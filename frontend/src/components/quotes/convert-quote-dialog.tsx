"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { quotesApi } from "@/lib/api/quotes";
import { jobWindowError, localToIso } from "@/lib/jobs/job-derivations";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";
import type { Quote } from "@/types";

interface ConvertQuoteDialogProps {
  workspaceId: string;
  quote: Quote | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * Convert an approved quote into a job and/or an invoice, optionally scheduling
 * the created job on the calendar in the same step. Leaving the window blank
 * lands the job unscheduled (it sits in the dispatch queue).
 */
export function ConvertQuoteDialog({
  workspaceId,
  quote,
  open,
  onOpenChange,
}: ConvertQuoteDialogProps) {
  const queryClient = useQueryClient();
  const [createJob, setCreateJob] = useState(true);
  const [createInvoice, setCreateInvoice] = useState(true);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");

  const reset = () => {
    setCreateJob(true);
    setCreateInvoice(true);
    setStart("");
    setEnd("");
  };

  const handleOpenChange = (next: boolean) => {
    if (!next) reset();
    onOpenChange(next);
  };

  const windowError = createJob ? jobWindowError(start, end) : "";

  const convertMutation = useMutation({
    mutationFn: () => {
      if (!quote) throw new Error("No quote selected");
      return quotesApi.convert(workspaceId, quote.id, {
        create_job: createJob,
        create_invoice: createInvoice,
        // Only send a window when both bounds are set and a job is created.
        scheduled_start: createJob ? localToIso(start) : null,
        scheduled_end: createJob ? localToIso(end) : null,
      });
    },
    onSuccess: (result) => {
      const parts: string[] = [];
      if (result.job_id) parts.push(start && end ? "scheduled job" : "job");
      if (result.invoice_id) parts.push("invoice");
      toast.success(
        parts.length ? `Converted to ${parts.join(" + ")}` : "Quote converted",
      );
      void queryClient.invalidateQueries({
        queryKey: queryKeys.quotes.all(workspaceId),
      });
      handleOpenChange(false);
    },
    onError: (err: unknown) =>
      toast.error(getApiErrorMessage(err, "Failed to convert quote")),
  });

  const canSubmit =
    (createJob || createInvoice) && !windowError && !convertMutation.isPending;

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-[480px]">
        <DialogHeader>
          <DialogTitle>Convert quote{quote ? ` ${quote.number}` : ""}</DialogTitle>
          <DialogDescription>
            Turn this accepted quote into scheduled work and/or an invoice. Pick a
            date to schedule the job now, or leave it blank to schedule later.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-1">
          <label className="flex items-center gap-2.5 text-sm">
            <input
              type="checkbox"
              className="size-4 accent-primary"
              checked={createJob}
              onChange={(e) => setCreateJob(e.target.checked)}
            />
            Create a job (work order)
          </label>

          {createJob ? (
            <div className="grid grid-cols-2 gap-3 pl-6">
              <div className="space-y-1.5">
                <Label htmlFor="convert-start">Scheduled start</Label>
                <Input
                  id="convert-start"
                  type="datetime-local"
                  value={start}
                  onChange={(e) => setStart(e.target.value)}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="convert-end">Scheduled end</Label>
                <Input
                  id="convert-end"
                  type="datetime-local"
                  value={end}
                  onChange={(e) => setEnd(e.target.value)}
                />
              </div>
            </div>
          ) : null}

          <label className="flex items-center gap-2.5 text-sm">
            <input
              type="checkbox"
              className="size-4 accent-primary"
              checked={createInvoice}
              onChange={(e) => setCreateInvoice(e.target.checked)}
            />
            Create an invoice
          </label>

          {windowError ? (
            <p className="text-sm text-destructive">{windowError}</p>
          ) : null}
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => handleOpenChange(false)}
            disabled={convertMutation.isPending}
          >
            Cancel
          </Button>
          <Button onClick={() => convertMutation.mutate()} disabled={!canSubmit}>
            {convertMutation.isPending ? (
              <Loader2 className="mr-1.5 size-4 animate-spin" />
            ) : null}
            Convert
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
