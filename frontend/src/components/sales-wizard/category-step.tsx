"use client";

/**
 * Product-line picker — the first real decision in the unified Quote Builder.
 * The rep chooses which lines this quote covers (landscape, permanent roofline,
 * bistro, seasonal Christmas). Only lines the workspace has configured are
 * offered; landscape is always available. Selection drives which builder
 * sections render and which categories the server prices.
 */
import type { CategoryKey, UseSalesWizardReturn } from "./use-sales-wizard";

interface CategoryStepProps {
  wizard: UseSalesWizardReturn;
}

interface CategoryMeta {
  key: CategoryKey;
  label: string;
  blurb: string;
}

const CATEGORY_META: CategoryMeta[] = [
  {
    key: "landscape",
    label: "Landscape Lighting",
    blurb: "Architectural & landscape fixtures — Good / Better / Best packages.",
  },
  {
    key: "permanent",
    label: "Permanent Holiday Lights",
    blurb: "Year-round LED roofline track, priced per linear foot + controller.",
  },
  {
    key: "bistro",
    label: "Bistro / String Lights",
    blurb: "Patio & pergola festoon lighting, priced per linear foot.",
  },
  {
    key: "christmas",
    label: "Christmas Lighting",
    blurb: "Seasonal roofline, trees, bushes & wreaths — with optional takedown.",
  },
];

/** Whether a line is offered by this workspace's pricing config. */
function isAvailable(wizard: UseSalesWizardReturn, key: CategoryKey): boolean {
  const p = wizard.pricing;
  switch (key) {
    case "landscape":
      return (p?.tiers?.length ?? 0) > 0;
    case "permanent":
      return Boolean(p?.permanent?.enabled);
    case "bistro":
      return Boolean(p?.bistro?.enabled) && (p?.bistro?.tiers?.length ?? 0) > 0;
    case "christmas":
      return Boolean(p?.christmas?.enabled);
    default:
      return false;
  }
}

export function CategoryStep({ wizard }: CategoryStepProps) {
  const available = CATEGORY_META.filter(
    (meta) => meta.key === "landscape" || isAvailable(wizard, meta.key),
  );

  return (
    <div className="cat-picker">
      {available.map((meta) => {
        const active = wizard.hasCategory(meta.key);
        return (
          <button
            key={meta.key}
            type="button"
            className={`care-tier cat-chip${active ? " selected" : ""}`}
            aria-pressed={active}
            onClick={() => wizard.toggleCategory(meta.key)}
          >
            <div className="cat-chip-check">{active ? "\u2713" : "+"}</div>
            <div className="care-tier-name">{meta.label}</div>
            <div className="care-tier-blurb">{meta.blurb}</div>
          </button>
        );
      })}
    </div>
  );
}

export { CATEGORY_META };
