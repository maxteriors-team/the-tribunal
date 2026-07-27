"use client";

/**
 * Service picker — the first real decision in the unified Quote Builder.
 *
 * A quote covers **one** service, so the three services a rep sells are chosen
 * exclusively (a radio group, not checkboxes): **Landscape Lighting**, **Holiday
 * Lights — Permanent** (year-round LED track), and **Christmas & Holiday
 * Lighting** (seasonal). Picking a service replaces the selection, so a quote can
 * never span two branches. Only the active service's product lines are offered,
 * and only landscape sells more than one line (landscape + bistro), so it is the
 * only service that renders an inner line picker. Services the workspace hasn't
 * configured are hidden; landscape is always available.
 */
import {
  Cable,
  Lightbulb,
  Snowflake,
  TreePine,
  Trees,
  type LucideIcon,
} from "lucide-react";

import type {
  CategoryKey,
  ServiceKey,
  UseSalesWizardReturn,
} from "./use-sales-wizard";

interface CategoryMeta {
  key: CategoryKey;
  label: string;
  blurb: string;
  /** Distinct glyph so each product line reads at a glance, not just as text. */
  Icon: LucideIcon;
}

const CATEGORY_META: CategoryMeta[] = [
  {
    key: "landscape",
    label: "Landscape Lighting",
    blurb: "Architectural & landscape fixtures — Good / Better / Best packages.",
    Icon: Trees,
  },
  {
    key: "permanent",
    label: "Holiday Lights — Permanent",
    blurb: "Year-round LED roofline track, priced per linear foot + controller.",
    Icon: Cable,
  },
  {
    key: "bistro",
    label: "Bistro Lights",
    blurb: "Patio & pergola festoon string lighting, priced per linear foot.",
    Icon: Lightbulb,
  },
  {
    key: "christmas",
    label: "Holiday Lights — Temporary",
    blurb: "Seasonal roofline, trees, bushes & wreaths — with optional takedown.",
    Icon: Snowflake,
  },
];

/** A sellable service — a visually separate group of related product lines. */
interface ServiceGroup {
  key: ServiceKey;
  label: string;
  blurb: string;
  /** Accent color that visually distinguishes this service in the builder. */
  accent: string;
  Icon: LucideIcon;
  categories: CategoryKey[];
}

/** Per-service accent colors, reused by the step headings for consistency. */
export const SERVICE_ACCENTS = {
  landscape: "#d4af5a", // gold — the native luxury accent
  permanent: "#6aa9d4", // ice blue — cool, year-round LED track
  christmas: "#3fa66a", // evergreen — festive, distinct from gold
} as const;

const SERVICE_GROUPS: ServiceGroup[] = [
  {
    key: "landscape",
    label: "Landscape Lighting",
    blurb: "Architectural & outdoor-living lighting, installed year-round.",
    accent: SERVICE_ACCENTS.landscape,
    Icon: Trees,
    categories: ["landscape", "bistro"],
  },
  {
    key: "permanent",
    label: "Holiday Lights \u2014 Permanent",
    blurb: "Year-round LED roofline track, lit for every holiday.",
    accent: SERVICE_ACCENTS.permanent,
    Icon: Cable,
    categories: ["permanent"],
  },
  {
    key: "christmas",
    label: "Christmas & Holiday Lighting",
    blurb: "Seasonal roofline, trees, bushes & wreaths \u2014 installed each season.",
    accent: SERVICE_ACCENTS.christmas,
    Icon: TreePine,
    categories: ["christmas"],
  },
];

interface CategoryStepProps {
  wizard: UseSalesWizardReturn;
}

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

function CategoryChip({
  wizard,
  meta,
}: {
  wizard: UseSalesWizardReturn;
  meta: CategoryMeta;
}) {
  const active = wizard.hasCategory(meta.key);
  return (
    <button
      type="button"
      className={`care-tier cat-chip${active ? " selected" : ""}`}
      aria-pressed={active}
      onClick={() => wizard.toggleCategory(meta.key)}
    >
      <div className="cat-chip-check">{active ? "\u2713" : "+"}</div>
      <div className="care-tier-name">
        <meta.Icon
          aria-hidden="true"
          style={{
            width: 16,
            height: 16,
            marginRight: 8,
            verticalAlign: "-3px",
            color: "var(--svc-accent)",
          }}
        />
        {meta.label}
      </div>
      <div className="care-tier-blurb">{meta.blurb}</div>
    </button>
  );
}

export function CategoryStep({ wizard }: CategoryStepProps) {
  return (
    <div className="svc-groups" role="radiogroup" aria-label="Service">
      {SERVICE_GROUPS.map((svc) => {
        // Only lines this workspace offers (landscape is always available). A
        // service with nothing left to sell isn't offered at all.
        const metas = svc.categories
          .map((key) => CATEGORY_META.find((m) => m.key === key))
          .filter((m): m is CategoryMeta => Boolean(m))
          .filter((m) => m.key === "landscape" || isAvailable(wizard, m.key));
        if (!metas.length) return null;
        const active = wizard.activeService === svc.key;
        return (
          <div
            key={svc.key}
            className={`svc-group${active ? " selected" : ""}`}
            style={{ "--svc-accent": svc.accent } as React.CSSProperties}
          >
            <button
              type="button"
              role="radio"
              aria-checked={active}
              className="svc-group-head svc-group-pick"
              onClick={() => wizard.setService(svc.key)}
            >
              <span className="svc-group-icon" aria-hidden="true">
                <svc.Icon className="svc-group-glyph" />
              </span>
              <span>
                <span className="svc-group-name">{svc.label}</span>
                <span className="svc-group-blurb">{svc.blurb}</span>
              </span>
              <span className="svc-group-check" aria-hidden="true">
                {active ? "\u2713" : ""}
              </span>
            </button>
            {/* Line picker only where a service sells more than one line. */}
            {active && metas.length > 1 ? (
              <div className="cat-picker">
                {metas.map((meta) => (
                  <CategoryChip key={meta.key} wizard={wizard} meta={meta} />
                ))}
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

export { CATEGORY_META };
