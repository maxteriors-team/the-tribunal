"use client";

/**
 * Title bar shown when the contact rail is rendered as a slide-over. The
 * enclosing Sheet supplies its own close control, so this stays a heading only
 * (two stacked close buttons used to overlap in the same corner).
 */
export function OverlayHeader() {
  return (
    <div className="flex shrink-0 items-center border-b p-4">
      <h3 className="font-semibold">Contact Details</h3>
    </div>
  );
}
