"use client";

import { useEffect, type KeyboardEvent } from "react";

import type { LandscapeWorkflowTab } from "@/lib/estimator/types";
import { cn } from "@/lib/utils";

const tabs: Array<{ value: LandscapeWorkflowTab; label: string }> = [
  { value: "drawing", label: "Drawing Sheet" },
  { value: "schedule", label: "Fixture Schedule" },
  { value: "bom", label: "BOM" },
  { value: "electrical", label: "Electrical" },
  { value: "proposal", label: "Proposal" },
  { value: "precon", label: "Pre-Con" },
];

function nextTabIndex(event: KeyboardEvent<HTMLButtonElement>, index: number) {
  if (event.key === "ArrowRight") return (index + 1) % tabs.length;
  if (event.key === "ArrowLeft") return (index - 1 + tabs.length) % tabs.length;
  if (event.key === "Home") return 0;
  if (event.key === "End") return tabs.length - 1;
  return null;
}

export function ProjectWorkflowTabs({
  value,
  onChange,
}: {
  value: LandscapeWorkflowTab;
  onChange: (value: LandscapeWorkflowTab) => void;
}) {
  useEffect(() => {
    const activeTab = document.getElementById(`landscape-tab-${value}`);
    if (!activeTab || typeof activeTab.scrollIntoView !== "function") return;
    const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    activeTab.scrollIntoView({
      behavior: reduceMotion ? "auto" : "smooth",
      block: "nearest",
      inline: "center",
    });
  }, [value]);

  return (
    <div className="ll-workflow-tabs overflow-x-auto border-b border-[#a98336] bg-[#090909] [scrollbar-color:#a98336_#090909] [scrollbar-width:thin]">
      <div
        className="mx-auto flex min-w-max max-w-[1800px] px-2 sm:px-4"
        role="tablist"
        aria-label="Landscape project workflow"
      >
        {tabs.map(({ value: tab, label }, index) => (
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
              const targetIndex = nextTabIndex(event, index);
              if (targetIndex === null) return;
              event.preventDefault();
              const next = tabs[targetIndex];
              onChange(next.value);
              document.getElementById(`landscape-tab-${next.value}`)?.focus();
            }}
            className={cn(
              "relative flex h-[42px] items-center justify-center whitespace-nowrap border-b-2 px-5 text-[11px] font-bold uppercase tracking-[0.11em] transition-[color,border-color] duration-150 focus-visible:z-10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[#e2b35f] motion-reduce:transition-none",
              value === tab
                ? "border-[#d1a252] text-white"
                : "border-transparent text-[#b9b7b2] hover:text-white",
            )}
          >
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}
