"use client";

import {
  DollarSign,
  Loader2,
  Play,
  Plus,
  Square,
  Trash2,
} from "lucide-react";
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
  useClockOut,
  useDeleteExpense,
  useDeleteTimeEntry,
  useJobExpenses,
  useJobProfitability,
  useJobTimeEntries,
} from "@/hooks/useJobCosting";
import { formatDate } from "@/lib/utils/date";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { formatCurrency } from "@/lib/utils/number";

interface JobCostingPanelProps {
  workspaceId: string;
  jobId: string;
}

/**
 * Field-execution panel for a job: clock in/out, logged time, expenses, and a
 * live P&L (revenue from the linked invoice minus labor and expense cost). Used
 * inside the job detail dialog; the layout is single-column so it reads on a
 * phone-width screen.
 */
export function JobCostingPanel({ workspaceId, jobId }: JobCostingPanelProps) {
  const { can } = useCapabilities();
  // Revenue, profit, and margin are billing data. Technicians (jobs:read only)
  // log their time/expenses but must not see what the customer pays or the
  // job's margin — mirror the backend billing:read gate on /profitability.
  const canViewPnl = can("billing:read");

  const timeEntries = useJobTimeEntries(workspaceId, jobId);
  const expenses = useJobExpenses(workspaceId, jobId);
  const pnl = useJobProfitability(workspaceId, jobId, canViewPnl);

  const clockIn = useClockIn(workspaceId, jobId);
  const clockOut = useClockOut(workspaceId, jobId);
  const deleteEntry = useDeleteTimeEntry(workspaceId, jobId);
  const addExpense = useAddExpense(workspaceId, jobId);
  const deleteExpense = useDeleteExpense(workspaceId, jobId);

  const [rate, setRate] = useState("");
  const [expenseDesc, setExpenseDesc] = useState("");
  const [expenseAmount, setExpenseAmount] = useState("");

  // Derive the running-timer state from the time entries (a running entry has
  // no ``ended_at``) rather than the P&L payload, so clock in/out still works
  // for technicians who cannot read profitability.
  const openTimer = (timeEntries.data ?? []).some((entry) => !entry.ended_at);
  const currency = pnl.data?.currency ?? "USD";

  const handleClockIn = () => {
    clockIn.mutate(
      { rate: rate === "" ? 0 : Number(rate) },
      {
        onSuccess: () => toast.success("Clocked in"),
        onError: (err) => toast.error(getApiErrorMessage(err, "Failed to clock in")),
      },
    );
  };

  const handleClockOut = () => {
    clockOut.mutate(undefined, {
      onSuccess: () => toast.success("Clocked out"),
      onError: (err) => toast.error(getApiErrorMessage(err, "Failed to clock out")),
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

  const busy = clockIn.isPending || clockOut.isPending;

  return (
    <div className="space-y-5">
      {/* P&L summary — billing:read only. Hidden from technicians so they never
          see customer revenue, profit, or margin. */}
      {canViewPnl && (
        <div className="rounded-lg border p-3">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-sm font-medium">Profitability</span>
            {openTimer && (
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
                <span className="text-muted-foreground">
                  Labor · {pnl.data.total_hours}h
                </span>
                <span className="text-right tabular-nums">
                  −{formatCurrency(pnl.data.labor_cost, currency)}
                </span>
                <span className="text-muted-foreground">Expenses</span>
                <span className="text-right tabular-nums">
                  −{formatCurrency(pnl.data.expense_cost, currency)}
                </span>
              </div>
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
        <div className="flex flex-wrap items-end gap-2">
          <div className="flex-1 space-y-1">
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
              onChange={(e) => setRate(e.target.value)}
              disabled={openTimer || busy}
            />
          </div>
          {openTimer ? (
            <Button variant="destructive" onClick={handleClockOut} disabled={busy}>
              {clockOut.isPending ? (
                <Loader2 className="mr-2 size-4 animate-spin" />
              ) : (
                <Square className="mr-2 size-4" />
              )}
              Clock out
            </Button>
          ) : (
            <Button onClick={handleClockIn} disabled={busy}>
              {clockIn.isPending ? (
                <Loader2 className="mr-2 size-4 animate-spin" />
              ) : (
                <Play className="mr-2 size-4" />
              )}
              Clock in
            </Button>
          )}
        </div>

        {(timeEntries.data ?? []).length > 0 && (
          <ul className="divide-y rounded-md border text-sm">
            {(timeEntries.data ?? []).map((entry) => (
              <li key={entry.id} className="flex items-center justify-between gap-2 px-3 py-2">
                <div className="min-w-0">
                  <div className="truncate">
                    {formatDate(entry.started_at, { pattern: "MMM d, h:mm a" })}
                    {entry.ended_at
                      ? ` · ${entry.duration_hours}h`
                      : " · running"}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {formatCurrency(entry.rate, currency)}/h ·{" "}
                    {formatCurrency(entry.labor_cost, currency)}
                  </div>
                </div>
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
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Expenses */}
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
                  <span className="tabular-nums">
                    {formatCurrency(expense.amount, currency)}
                  </span>
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
    </div>
  );
}
