"use client";

/**
 * The cross-sell prompt, surfaced inline in the Quote Builder at save time.
 *
 * A roof job with no gutters on it is the single biggest lever on average job
 * value, and it only pays if the rep is told while they can still act. So this
 * is not a toast: it stays on screen next to the save button, and it leads with
 * the action ("Add gutters", pre-filtered to that category in the price book)
 * rather than with the complaint.
 *
 * Two modes, both from the workspace's own config:
 *
 * - **Advisory** — the quote already saved. The prompt is a second chance, and
 *   dismissing it costs nothing but a reason.
 * - **Blocking** — the quote did *not* save. The copy says so plainly, because a
 *   rep who believes a proposal is sent when it is not loses the job outright.
 *
 * Dismissing records *why* server-side, which is what separates "the customer
 * declined" from "nobody asked" in attach reporting later.
 */
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { CatalogPicker } from "@/components/catalog/catalog-picker";
import { getApiErrorMessage } from "@/lib/utils/errors";
import type { CatalogItem } from "@/types";
import type { AttachWarning } from "@/types/sales-wizard";

import type { UseSalesWizardReturn } from "./use-sales-wizard";

/**
 * The prompt's two actions, wired to the builder, so every save surface behaves
 * identically instead of each screen inventing its own handling.
 */
export function useAttachPromptActions(wizard: UseSalesWizardReturn) {
  const { addCatalogCharge, dismissAttach } = wizard;
  return useMemo(
    () => ({
      /** Add the picked price-book item to the quote as a priced line. */
      add: (item: CatalogItem) => {
        addCatalogCharge(item);
        toast.success(`${item.name} added to the quote`);
      },
      /** Skip the prompt; the reason is recorded when the quote is saved. */
      dismiss: (reason: string | null) => {
        dismissAttach(reason);
        toast.success(
          reason ? `Skipped — recorded as “${reason}”` : "Add-on skipped",
        );
      },
      /** Message for a failed save, kept honest about a blocking rule. */
      saveErrorMessage: (error: unknown) =>
        getApiErrorMessage(
          error,
          "Could not save the proposal. Please try again.",
        ),
    }),
    [addCatalogCharge, dismissAttach],
  );
}

interface AttachPromptProps {
  warning: AttachWarning;
  /** Append the picked price-book item to the quote. */
  onAdd: (item: CatalogItem) => void;
  /** Save again, recording the dismissal and its reason. */
  onDismiss: (reason: string | null) => void;
  busy?: boolean;
}

export function AttachPrompt({
  warning,
  onAdd,
  onDismiss,
  busy = false,
}: AttachPromptProps) {
  const reasons = warning.dismissal_reasons ?? [];
  const mustGiveReason = warning.require_dismissal_reason && reasons.length > 0;
  const [reason, setReason] = useState("");

  const blocking = warning.mode === "blocking";
  const canDismiss = !busy && (!mustGiveReason || reason !== "");

  return (
    <section
      className={`attach-prompt${blocking ? " blocking" : ""}`}
      // Assertive for a blocking rule: the save the rep just asked for did not
      // happen, and that has to interrupt. Advisory is polite by comparison.
      role={blocking ? "alert" : "status"}
      aria-live={blocking ? "assertive" : "polite"}
    >
      <h2 className="attach-prompt-title">
        {blocking ? "Quote not saved" : "Add-on opportunity"}
      </h2>

      <p className="attach-prompt-body">{warning.message}</p>

      <div className="attach-prompt-actions">
        {warning.suggested_categories.map((category) => (
          <CatalogPicker
            key={category}
            category={category}
            label={`Add ${category}`}
            disabled={busy}
            onPick={onAdd}
            // Render in the builder's own theme; the dropdown itself portals
            // out to the app shell and keeps the standard picker styling.
            triggerClassName="attach-prompt-add"
          />
        ))}

        <span className="attach-prompt-sep" />

        {mustGiveReason && (
          <>
            <label className="sr-only" htmlFor="attach-dismiss-reason">
              Reason for skipping the add-on
            </label>
            <select
              id="attach-dismiss-reason"
              className="attach-prompt-reason"
              value={reason}
              disabled={busy}
              onChange={(event) => setReason(event.target.value)}
            >
              <option value="">Reason for skipping…</option>
              {reasons.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </>
        )}

        <button
          type="button"
          className="send-email-nav-btn"
          disabled={!canDismiss}
          onClick={() => onDismiss(reason || null)}
        >
          {blocking ? "Skip & save anyway" : "Skip"}
        </button>
      </div>

      {mustGiveReason && reason === "" && (
        <p className="attach-prompt-note">
          Pick a reason to skip. It is what tells you later whether customers are
          declining this add-on or nobody is offering it.
        </p>
      )}
    </section>
  );
}
