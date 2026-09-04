"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, Loader2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { HandoffImages } from "@/components/jobs/handoff-images";
import { TechnicianSelect } from "@/components/jobs/technician-select";
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
import { useCapabilities } from "@/hooks/useCapabilities";
import { useWorkspaceCrews, useWorkspaceTechnicians } from "@/hooks/useJobs";
import { quotesApi } from "@/lib/api/quotes";
import { jobWindowError, localToIso } from "@/lib/jobs/job-derivations";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";
import type { Quote, QuoteConvertResult } from "@/types";

import { depositPaymentMethodLabel } from "./record-deposit-dialog";

interface ConvertQuoteDialogProps {
  workspaceId: string;
  quote: Quote | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  mode?: "closeout" | "copy-to-job";
}

const money = (value: number | null | undefined, currency = "USD") =>
  new Intl.NumberFormat("en-US", { style: "currency", currency }).format(value ?? 0);

/** One authoritative accepted-quote closeout: deposit truth, schedule, assignment. */
export function ConvertQuoteDialog({
  workspaceId,
  quote,
  open,
  onOpenChange,
  mode = "closeout",
}: ConvertQuoteDialogProps) {
  const copyToJob = mode === "copy-to-job";
  const queryClient = useQueryClient();
  const { can } = useCapabilities();
  const canCreateInvoice = can("billing:write");
  const [createJob, setCreateJob] = useState(true);
  const [createInvoice, setCreateInvoice] = useState(!copyToJob);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [crewId, setCrewId] = useState("");
  const [selectedTechnicianIds, setSelectedTechnicianIds] = useState<string[]>([]);
  const [confirmUnpaidDeposit, setConfirmUnpaidDeposit] = useState(false);
  const [result, setResult] = useState<QuoteConvertResult | null>(null);
  const techniciansQuery = useWorkspaceTechnicians(workspaceId, open && createJob);
  const crewsQuery = useWorkspaceCrews(workspaceId, open && createJob);
  const technicians = techniciansQuery.data?.items ?? [];
  const crews = crewsQuery.data?.items.filter((crew) => crew.is_active) ?? [];

  const reset = () => {
    setCreateJob(true);
    setCreateInvoice(!copyToJob);
    setStart("");
    setEnd("");
    setCrewId("");
    setSelectedTechnicianIds([]);
    setConfirmUnpaidDeposit(false);
    setResult(null);
  };
  const handleOpenChange = (next: boolean) => {
    if (!next) reset();
    onOpenChange(next);
  };

  const requiredDeposit = Boolean(quote?.deposit_required);
  const paidDeposit = Boolean(quote?.deposit_paid);
  const depositAmount = quote?.deposit_amount ?? null;
  const paidMethod = depositPaymentMethodLabel(quote?.deposit_payment_method);
  const hasExistingInvoice = Boolean(quote?.converted_invoice_id);
  const shouldCreateInvoice = hasExistingInvoice || (canCreateInvoice && createInvoice);
  const windowError = createJob
    ? !start || !end
      ? "Set both start and end."
      : jobWindowError(start, end)
    : "";
  const unpaidBlocked = createJob && requiredDeposit && !confirmUnpaidDeposit;

  const convertMutation = useMutation({
    mutationFn: () => {
      if (!quote) throw new Error("No quote selected");
      return quotesApi.convert(workspaceId, quote.id, {
        create_job: createJob,
        // Conversion flags describe the desired final handoff; retain an invoice already linked.
        create_invoice: shouldCreateInvoice,
        scheduled_start: createJob ? localToIso(start) : null,
        scheduled_end: createJob ? localToIso(end) : null,
        crew_id: createJob && crewId ? crewId : null,
        technician_ids: createJob ? selectedTechnicianIds : [],
        confirm_unpaid_deposit: confirmUnpaidDeposit,
      });
    },
    onSuccess: (converted) => {
      setResult(converted);
      void queryClient.invalidateQueries({ queryKey: queryKeys.quotes.all(workspaceId) });
      if (converted.job_id) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.jobs.all(workspaceId) });
      }
      toast.success(
        converted.idempotent_replay
          ? "Existing handoff opened"
          : copyToJob
            ? "Job created and scheduled"
            : "Installation scheduled",
      );
    },
    onError: (error: unknown) => toast.error(getApiErrorMessage(error, "Failed to convert quote")),
  });

  const canSubmit =
    Boolean(quote) &&
    (createJob || shouldCreateInvoice) &&
    !windowError &&
    !unpaidBlocked &&
    !convertMutation.isPending;

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-[560px]">
        <DialogHeader>
          <DialogTitle>
            {copyToJob ? "Copy" : "Close out"} quote{quote ? ` ${quote.number}` : ""}
            {copyToJob ? " to a job" : ""}
          </DialogTitle>
          <DialogDescription>
            {copyToJob
              ? "Copy the approved scope into a scheduled job, then assign the installation team."
              : "Confirm payment truth, schedule the work, then share the selected plan automatically."}
          </DialogDescription>
        </DialogHeader>

        {result ? (
          <div className="space-y-4 py-2">
            <div className="rounded-lg border bg-muted/30 p-4">
              <p className="font-medium">
                {copyToJob ? "Job created and scheduled" : "Authoritative handoff saved"}
              </p>
              <p className="mt-1 text-sm text-muted-foreground">
                Crew delivery: {result.crew_notification.status.replace("_", " ")} ·{" "}
                {result.crew_notification.sent_count}/{result.crew_notification.recipient_count}{" "}
                recipients
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              {result.job_id ? (
                <Button asChild>
                  <Link href={`/calendar?job=${result.job_id}`}>
                    Open job <ExternalLink />
                  </Link>
                </Button>
              ) : null}
              {result.invoice_id ? (
                <Button variant="outline" asChild>
                  <Link href={`/invoices/${result.invoice_id}`}>Open invoice</Link>
                </Button>
              ) : null}
            </div>
          </div>
        ) : (
          <div className="space-y-5 py-1">
            {copyToJob ? (
              <section className="rounded-lg border p-4" aria-labelledby="job-details-step">
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  1 · Job details
                </p>
                <h3 id="job-details-step" className="mt-1 font-medium">
                  Copied from {quote?.number}
                </h3>
                <dl className="mt-3 space-y-2 text-sm">
                  <div>
                    <dt className="text-xs text-muted-foreground">Title</dt>
                    <dd>{quote?.title || quote?.number || "Untitled job"}</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-muted-foreground">Job description</dt>
                    <dd className="whitespace-pre-wrap text-muted-foreground">
                      {quote?.notes?.trim() || "No job description added"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-muted-foreground">Installation layout</dt>
                    <dd className="text-muted-foreground">
                      {quote?.lighting_project_id
                        ? "Linked layout included"
                        : "No layout linked to this quote"}
                    </dd>
                  </div>
                </dl>
              </section>
            ) : null}

            <section className="rounded-lg border p-4" aria-labelledby="deposit-step">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {copyToJob ? "2" : "1"} · Deposit
              </p>
              <h3 id="deposit-step" className="mt-1 font-medium">
                {paidDeposit
                  ? [
                      "Paid",
                      paidMethod,
                      quote?.deposit_paid_at
                        ? new Date(quote.deposit_paid_at).toLocaleDateString()
                        : null,
                    ]
                      .filter(Boolean)
                      .join(" · ")
                  : requiredDeposit
                    ? `Due · ${money(depositAmount, quote?.currency)}`
                    : "No deposit required"}
              </h3>
              {requiredDeposit ? (
                <>
                  <p className="mt-1 text-sm text-amber-700 dark:text-amber-300">
                    No deposit has been recorded yet. Scheduling is allowed only after explicit
                    confirmation.
                  </p>
                  {quote?.public_token ? (
                    <Button variant="link" className="h-auto px-0" asChild>
                      <Link href={`/p/quotes/${quote.public_token}`} target="_blank">
                        Open customer payment page <ExternalLink />
                      </Link>
                    </Button>
                  ) : null}
                  <label className="mt-2 flex items-start gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={confirmUnpaidDeposit}
                      onChange={(event) => setConfirmUnpaidDeposit(event.target.checked)}
                    />
                    Schedule with the required deposit still unpaid
                  </label>
                </>
              ) : null}
            </section>

            <section className="rounded-lg border p-4" aria-labelledby="schedule-step">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {copyToJob ? "3" : "2"} · Schedule
              </p>
              <h3 id="schedule-step" className="mt-1 font-medium">
                Installation window
              </h3>
              {copyToJob ? (
                <p className="mt-1 text-sm text-muted-foreground">
                  A field-service job will be added to the shared calendar.
                </p>
              ) : (
                <label className="mt-3 flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={createJob}
                    onChange={(event) => setCreateJob(event.target.checked)}
                  />{" "}
                  Create a field-service job
                </label>
              )}
              {createJob ? (
                <div className="mt-3 grid grid-cols-2 gap-3">
                  <div className="space-y-1.5">
                    <Label htmlFor="convert-start">Scheduled start</Label>
                    <Input
                      id="convert-start"
                      type="datetime-local"
                      required
                      value={start}
                      onChange={(event) => setStart(event.target.value)}
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="convert-end">Scheduled end</Label>
                    <Input
                      id="convert-end"
                      type="datetime-local"
                      required
                      value={end}
                      onChange={(event) => setEnd(event.target.value)}
                    />
                  </div>
                </div>
              ) : null}
              {hasExistingInvoice ? (
                <p className="mt-3 text-sm text-muted-foreground">
                  The existing invoice will stay linked to this job.
                </p>
              ) : canCreateInvoice ? (
                <label className="mt-3 flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={createInvoice}
                    onChange={(event) => setCreateInvoice(event.target.checked)}
                  />{" "}
                  {copyToJob ? "Also create an invoice" : "Create an invoice"}
                </label>
              ) : (
                <p className="mt-3 text-sm text-muted-foreground">
                  Billing access is required to create an invoice. This will schedule the job
                  without one.
                </p>
              )}
              {windowError ? <p className="mt-2 text-sm text-destructive">{windowError}</p> : null}
            </section>

            {createJob && quote ? (
              <HandoffImages mode="quote-edit" workspaceId={workspaceId} quoteId={quote.id} />
            ) : null}

            {createJob ? (
              <section className="rounded-lg border p-4" aria-labelledby="team-step">
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  {copyToJob ? "4" : "3"} · Installation team
                </p>
                <h3 id="team-step" className="mt-1 font-medium">
                  Crew and members
                </h3>
                <div className="mt-3 space-y-1.5">
                  <Label htmlFor="convert-crew">Route to crew</Label>
                  <select
                    id="convert-crew"
                    className="h-10 w-full rounded-md border bg-background px-3 text-sm"
                    value={crewId}
                    onChange={(event) => setCrewId(event.target.value)}
                  >
                    <option value="">No crew route</option>
                    {crews.map((crew) => (
                      <option key={crew.id} value={crew.id}>
                        {crew.name} · {crew.technician_count} technicians
                      </option>
                    ))}
                  </select>
                </div>
                <div className="mt-3 space-y-1.5">
                  <Label>Direct member assignments</Label>
                  {techniciansQuery.isPending ? (
                    <p className="text-sm text-muted-foreground">Loading technicians…</p>
                  ) : (
                    <TechnicianSelect
                      technicians={technicians}
                      selectedIds={selectedTechnicianIds}
                      onToggle={(id) =>
                        setSelectedTechnicianIds((current) =>
                          current.includes(id)
                            ? current.filter((entry) => entry !== id)
                            : [...current, id],
                        )
                      }
                    />
                  )}
                </div>
                <p className="mt-3 text-xs text-muted-foreground">
                  {quote?.lighting_project_id
                    ? "The selected installation diagram will be shared automatically after scheduling."
                    : "This quote has no linked installation diagram."}
                </p>
              </section>
            ) : null}
          </div>
        )}

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => handleOpenChange(false)}
            disabled={convertMutation.isPending}
          >
            {result ? "Close" : "Cancel"}
          </Button>
          {!result ? (
            <Button onClick={() => convertMutation.mutate()} disabled={!canSubmit}>
              {convertMutation.isPending ? (
                <Loader2 className="mr-1.5 size-4 animate-spin" />
              ) : null}
              {copyToJob ? "Copy to job" : "Schedule installation"}
            </Button>
          ) : null}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
