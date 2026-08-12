"use client";

import { ClipboardCheck, FileText, Lightbulb, ListChecks, PackageOpen, Zap } from "lucide-react";

import type { LandscapeWorkflowTab } from "@/lib/estimator/types";
import { cn } from "@/lib/utils";

const tabs: Array<{
  value: LandscapeWorkflowTab;
  label: string;
  icon: typeof FileText;
}> = [
  { value: "drawing", label: "Drawing Sheet", icon: FileText },
  { value: "schedule", label: "Fixture Schedule", icon: ListChecks },
  { value: "bom", label: "BOM", icon: PackageOpen },
  { value: "electrical", label: "Electrical", icon: Zap },
  { value: "proposal", label: "Proposal", icon: Lightbulb },
  { value: "precon", label: "Pre-Con", icon: ClipboardCheck },
];

export function ProjectWorkflowTabs({
  value,
  onChange,
}: {
  value: LandscapeWorkflowTab;
  onChange: (value: LandscapeWorkflowTab) => void;
}) {
  return (
    <div className="overflow-x-auto border-b border-white/10 bg-neutral-950 [scrollbar-width:thin]">
      <div
        className="mx-auto flex min-w-max max-w-[1800px] px-2 sm:px-4"
        role="tablist"
        aria-label="Landscape project workflow"
      >
        {tabs.map(({ value: tab, label, icon: Icon }) => (
          <button
            key={tab}
            id={`landscape-tab-${tab}`}
            type="button"
            role="tab"
            aria-selected={value === tab}
            aria-controls={`landscape-panel-${tab}`}
            tabIndex={value === tab ? 0 : -1}
            onClick={() => onChange(tab)}
            onKeyDown={(event) => {
              const index = tabs.findIndex((entry) => entry.value === tab);
              const direction = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
              if (!direction) return;
              event.preventDefault();
              const next = tabs[(index + direction + tabs.length) % tabs.length];
              onChange(next.value);
              document.getElementById(`landscape-tab-${next.value}`)?.focus();
            }}
            className={cn(
              "relative flex h-12 min-w-32 items-center justify-center gap-2 border-b-2 px-4 text-xs font-semibold uppercase tracking-[0.08em] transition-[color,border-color,background-color] duration-150 focus-visible:z-10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400 motion-reduce:transition-none",
              value === tab
                ? "border-amber-400 bg-white/[0.06] text-amber-300"
                : "border-transparent text-neutral-400 hover:bg-white/[0.04] hover:text-white",
            )}
          >
            <Icon className="size-4" aria-hidden="true" />
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}
