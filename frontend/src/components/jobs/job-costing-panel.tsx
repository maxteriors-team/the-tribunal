"use client";

import { DollarSign, Loader2, Pause, Play, Plus, Square, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useCapabilities } from "@/hooks/useCapabilities";
import {
  useAddExpense,
  useClockIn,
  useDeleteExpense,
  useDeleteTimeEntry,
  useEndJobTimer,
  useJobExpenses,
  useJobProfitability,
  useJobTimeEntries,
  usePauseJobTimer,
} from "@/hooks/useJobCosting";
import type { JobStatus } from "@/lib/api/jobs";
import { formatDate } from "@/lib/utils/date";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { formatCurrency } from "@/lib/utils/number";

interface JobCostingPanelProps {
  workspaceId: string;
  jobId: string;
  contactId: number;
  jobStatus: JobStatus;
}

/**
 * Field-execution panel for start/pause/end timers, logged time, expenses, and
 * billing-gated P&L. Timer controls are per-user, so one technician cannot stop
 * another technician's active interval.
 */
export function JobCostingPanel({
  workspaceId,
  jobId,
  contactId,
  jobStatus,
}: JobCostingPanelProps) {
  const { can } = useCapabilities();
  const canViewPnl = can("billing:read");
  const canSetRate = can("billing:write");
  const canManageAttendance = can("attendance:manage");
  // The backend independently strips these values; match its permission here.
  const canSeeCosts = can("billing:read");

  const timeEntries = useJobTimeEntries(workspaceId, jobId);
  const expenses = useJobExpenses(workspaceId, jobId, canSeeCosts);
  const pnl = useJobProfitability(workspaceId, jobId, canViewPnl);

  const clockIn = useClockIn(workspaceId, jobId, contactId);
  const pauseTimer = usePauseJobTimer(workspaceId, jobId, contactId);
  const endTimer = useEndJobTimer(workspaceId, jobId, contactId);
  const deleteEntry = useDeleteTimeEntry(workspaceId, jobId, contactId);
  const addExpense = useAddExpense(workspaceId, jobId);
  const deleteExpense = useDeleteExpense(workspaceId, jobId);

  const [rate, setRate] = useState("");
  const [expenseDesc, setExpenseDesc] = useState("");
  const [expenseAmount, setExpenseAmount] = useState("");

  const entries = timeEntries.data ?? [];
  const ownTimerEntries = entries.filter(
    (entry) => entry.is_mine && entry.stop_reason !== "manual",
  );
  const openTimer = ownTimerEntries.find((entry) => !entry.ended_at);
  const latestTimer = ownTimerEntries[0];
  const timerEnded =
    latestTimer?.stop_reason === "ended" ||
    Boolean(latestTimer?.ended_at && latestTimer.stop_reason == null);
  const timerPaused = latestTimer?.stop_reason === "paused";
  const anyTimerRunning = entries.some((entry) => !entry.ended_at);
  const jobClosed = jobStatus === "completed" || jobStatus === "cancelled";
  const currency = pnl.data?.currency ?? "USD";

  const handleClockIn = () => {
    clockIn.mutate(
      { rate: !canSetRate || rate === "" ? 0 : Number(rate) },
      {
        onSuccess: () => toast.success(timerPaused ? "Timer resumed" : "Job timer started"),
        onError: (err) => toast.error(getApiErrorMessage(err, "Failed to start timer")),
      },
    );
  };

  const handlePause = () => {
    pauseTimer.mutate(undefined, {
      onSuccess: () => toast.success("Timer paused"),
      onError: (err) => toast.error(getApiErrorMessage(err, "Failed to pause timer")),
    });
  };

  const handleEnd = () => {
    endTimer.mutate(undefined, {
      onSuccess: () => toast.success("Job timer ended"),
      onError: (err) => toast.error(getApiErrorMessage(err, "Failed to end timer")),
    });
  };

  const handleAddExpense = () => {
    const amount = Number(expenseAmount);
    if (!expenseDesc.trim() || !(amount > 0)) {
      toast.error("Enter a description and an amount");
      return;
    }
    addExpense.mutate(
      { description: expenseDesc.trim(), amount },
      {
        onSuccess: () => {
          toast.success("Expense added");
          setExpenseDesc("");
          setExpenseAmount("");
        },
        onError: (err) => toast.error(getApiErrorMessage(err, "Failed to add expense")),
      },
    );
  };

  const busy =
    timeEntries.isPending ||
    timeEntries.isError ||
    clockIn.isPending ||
    pauseTimer.isPending ||
    endTimer.isPending;

  return (
    <div className="space-y-5">
      {/* P&L summary — billing:read only. Hidden from technicians so they never
          see customer revenue, profit, or margin. */}
      {canViewPnl && (
        <div className="rounded-lg border p-3">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-sm font-medium">Profitability</span>
            {anyTimerRunning && (
              <Badge variant="secondary" className="gap-1">
                <span className="size-1.5 animate-pulse rounded-full bg-emerald-500" />
                Timer running
              </Badge>
            )}
          </div>
          {pnl.isLoading || !pnl.data ? (
            <p className="text-sm text-muted-foreground">Calculating…</p>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm">
                <span className="text-muted-foreground">Revenue</span>
                <span className="text-right tabular-nums">
                  {formatCurrency(pnl.data.revenue, currency)}
                </span>
                <span className="text-muted-foreground">Labor · {pnl.data.total_hours}h</span>
                <span className="text-right tabular-nums">
                  −{formatCurrency(pnl.data.labor_cost, currency)}
                </span>
                <span className="text-muted-foreground">Expenses</span>
                <span className="text-right tabular-nums">
                  −{formatCurrency(pnl.data.expense_cost, currency)}
                </span>
                {/* Materials come from the inventory ledger, never from an
                    expense row, so both lines can be non-zero without either
                    double-counting the other. */}
                <span className="text-muted-foreground">Materials</span>
                <span className="text-right tabular-nums">
                  −{formatCurrency(pnl.data.material_cost, currency)}
                </span>
              </div>
              {pnl.data.material_cost > 0 && pnl.data.expense_cost > 0 && (
                <p className="mt-2 text-xs text-muted-foreground">
                  Materials are stock pulled from inventory; expenses are costs entered by hand.
                  They are counted separately.
                </p>
              )}
              <div className="mt-2 flex items-center justify-between border-t pt-2">
                <span className="text-sm font-medium">Profit</span>
                <span
                  className={`text-base font-semibold tabular-nums ${
                    pnl.data.profit >= 0 ? "text-emerald-600" : "text-destructive"
                  }`}
                >
                  {formatCurrency(pnl.data.profit, currency)}
                  {pnl.data.margin !== null && pnl.data.margin !== undefined && (
                    <span className="ml-1 text-xs font-normal text-muted-foreground">
                      ({Math.round(pnl.data.margin * 100)}%)
                    </span>
                  )}
                </span>
              </div>
            </>
          )}
        </div>
      )}

      {/* Time tracking */}
      <div className="space-y-2">
        <div className="flex items-center justify-between gap-2">
          <Label className="text-sm">Job timer</Label>
          {openTimer ? (
            <Badge variant="secondary" className="gap-1">
              <span className="size-1.5 animate-pulse rounded-full bg-emerald-500" />
              Running
            </Badge>
          ) : timerEnded ? (
            <Badge variant="outline">Ended</Badge>
          ) : timerPaused ? (
            <Badge variant="outline">Paused</Badge>
          ) : null}
        </div>

        <div className="flex flex-wrap items-end gap-2">
          {canSetRate && (
            <div className="min-w-36 flex-1 space-y-1">
              <Label htmlFor="clock-rate" className="text-xs">
                Hourly rate
              </Label>
              <Input
                id="clock-rate"
                type="number"
                min="0"
                step="0.01"
                inputMode="decimal"
                placeholder="0.00"
                value={rate}
                onChange={(event) => setRate(event.target.value)}
                disabled={Boolean(openTimer) || busy || jobClosed}
              />
            </div>
          )}

          {!jobClosed && (
            <>
              {openTimer ? (
                <Button variant="secondary" onClick={handlePause} disabled={busy}>
                  {pauseTimer.isPending ? (
                    <Loader2 className="mr-2 size-4 animate-spin" />
                  ) : (
                    <Pause className="mr-2 size-4" />
                  )}
                  Pause
                </Button>
              ) : (
                <Button onClick={handleClockIn} disabled={busy}>
                  {clockIn.isPending ? (
                    <Loader2 className="mr-2 size-4 animate-spin" />
                  ) : (
                    <Play className="mr-2 size-4" />
                  )}
                  {timerPaused ? "Resume" : "Start"}
                </Button>
              )}
              {(openTimer || timerPaused) && (
                <Button variant="destructive" onClick={handleEnd} disabled={busy}>
                  {endTimer.isPending ? (
                    <Loader2 className="mr-2 size-4 animate-spin" />
                  ) : (
                    <Square className="mr-2 size-4" />
                  )}
                  End
                </Button>
              )}
            </>
          )}
        </div>

        {jobClosed && (
          <p className="text-xs text-muted-foreground">Timers are closed for {jobStatus} jobs.</p>
        )}
        {timeEntries.isError && (
          <p className="text-xs text-destructive">Job time could not be loaded.</p>
        )}

        {entries.length > 0 ? (
          <ul className="divide-y rounded-md border text-sm">
            {entries.map((entry) => (
              <li
                key={entry.id}
                className="flex items-center justify-between gap-2 px-3 py-2"
              >
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="truncate">
                      {formatDate(entry.started_at, { pattern: "MMM d, h:mm a" })}
                      {entry.ended_at ? ` · ${entry.duration_hours}h` : " · running"}
                    </span>
                    {entry.is_mine && (
                      <Badge variant="outline" className="h-5 px-1.5 text-[10px]">
                        You
                      </Badge>
                    )}
                    {entry.stop_reason && entry.stop_reason !== "manual" && (
                      <span className="text-xs capitalize text-muted-foreground">
                        {entry.stop_reason}
                      </span>
                    )}
                  </div>
                  {canSeeCosts && (
                    <div className="text-xs text-muted-foreground">
                      {formatCurrency(entry.rate, currency)}/h ·{" "}
                      {formatCurrency(entry.labor_cost, currency)}
                    </div>
                  )}
                </div>
                {(entry.is_mine || canManageAttendance) && (
                  <Button
                    variant="ghost"
                    size="icon"
                    className="size-7 shrink-0 text-muted-foreground hover:text-destructive"
                    onClick={() => deleteEntry.mutate(entry.id)}
                    disabled={deleteEntry.isPending}
                    aria-label="Delete time entry"
                  >
                    <Trash2 className="size-3.5" />
                  </Button>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <p className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">
            No time recorded yet.
          </p>
        )}
      </div>

      {/* Expenses — every row is a dollar amount, so billing permission gates it. */}
      {canSeeCosts && (
        <div className="space-y-2">
          <Label className="flex items-center gap-2 text-sm">
            <DollarSign className="size-4" />
            Expenses
          </Label>
          <div className="flex items-end gap-2">
            <Input
              placeholder="Description"
              value={expenseDesc}
              onChange={(e) => setExpenseDesc(e.target.value)}
              className="flex-1"
            />
            <Input
              type="number"
              min="0"
              step="0.01"
              inputMode="decimal"
              placeholder="Amount"
              value={expenseAmount}
              onChange={(e) => setExpenseAmount(e.target.value)}
              className="w-28"
            />
            <Button
              variant="secondary"
              size="icon"
              onClick={handleAddExpense}
              disabled={addExpense.isPending}
              aria-label="Add expense"
            >
              {addExpense.isPending ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Plus className="size-4" />
              )}
            </Button>
          </div>

          {(expenses.data ?? []).length > 0 && (
            <ul className="divide-y rounded-md border text-sm">
              {(expenses.data ?? []).map((expense) => (
                <li key={expense.id} className="flex items-center justify-between gap-2 px-3 py-2">
                  <div className="min-w-0">
                    <div className="truncate">{expense.description}</div>
                    {expense.category && (
                      <div className="text-xs text-muted-foreground">{expense.category}</div>
                    )}
                  </div>
                  <div className="flex items-center gap-1">
                    <span className="tabular-nums">{formatCurrency(expense.amount, currency)}</span>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="size-7 shrink-0 text-muted-foreground hover:text-destructive"
                      onClick={() => deleteExpense.mutate(expense.id)}
                      disabled={deleteExpense.isPending}
                      aria-label="Delete expense"
                    >
                      <Trash2 className="size-3.5" />
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
