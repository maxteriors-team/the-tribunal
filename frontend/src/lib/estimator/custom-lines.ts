/**
 * Standalone estimate lines — the rep's escape hatch from the price book.
 *
 * Packages and the decor catalog cover the work we sell every day. This covers
 * the rest: a bucket-truck day, hand-tying garland on a balcony, pulling the
 * last company's clips. A line here rides on top of whichever package the
 * customer picks (and on top of à la carte pricing), so nothing has to be faked
 * into a decor category to land one job.
 *
 * Drafts hold raw input strings, because a half-typed "12" must not price as
 * $12: only complete rows convert into request lines, and every dollar on the
 * estimate still comes back computed from the server.
 */
import type { EstimateCustomLine } from "@/types/estimate";

/** Which half of the comparison a line is billed on. */
export type CustomLineSide = EstimateCustomLine["side"];

export interface CustomLineDraft {
  /** Local-only row id, so editing one row never re-keys the others. */
  id: string;
  label: string;
  /** Raw input text; blank means "one". */
  quantity: string;
  /** Raw input text; blank means the row isn't priced yet. */
  unitPrice: string;
  side: CustomLineSide;
}

/** The server caps a request at 20 lines (`EstimateCustomLine` max_length). */
export const MAX_CUSTOM_LINES = 20;

let draftCounter = 0;

export function newCustomLineDraft(side: CustomLineSide): CustomLineDraft {
  draftCounter += 1;
  return {
    id: `line-${Date.now().toString(36)}-${draftCounter}`,
    label: "",
    quantity: "1",
    unitPrice: "",
    side,
  };
}

function parsePositive(raw: string, fallback: number): number | null {
  const text = raw.trim();
  if (text === "") return fallback;
  const value = Number(text);
  return Number.isFinite(value) ? value : null;
}

/**
 * The complete rows, as the estimate request carries them.
 *
 * A row is complete once it has a label and a price — an unnamed or unpriced
 * row is still being typed, and sending it would make the total jump around
 * under the rep's hands mid-keystroke. A free line ($0, "included") is
 * deliberately allowed; a negative one is not (use a discount on the quote).
 */
export function toEstimateCustomLines(
  drafts: readonly CustomLineDraft[],
): EstimateCustomLine[] {
  const lines: EstimateCustomLine[] = [];
  for (const draft of drafts) {
    const label = draft.label.trim();
    const quantity = parsePositive(draft.quantity, 1);
    const unitPrice = parsePositive(draft.unitPrice, Number.NaN);
    if (
      label === "" ||
      quantity === null ||
      quantity <= 0 ||
      unitPrice === null ||
      !Number.isFinite(unitPrice) ||
      unitPrice < 0
    ) {
      continue;
    }
    lines.push({ label, quantity, unit_price: unitPrice, side: draft.side });
    if (lines.length >= MAX_CUSTOM_LINES) break;
  }
  return lines;
}
