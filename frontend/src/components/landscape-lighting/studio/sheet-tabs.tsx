"use client";

import { Copy, Plus, Trash2 } from "lucide-react";

import type { DesignerShot } from "@/components/estimator/proposal-host";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function SheetTabs({
  shots,
  activeShotId,
  atLimit,
  onSelect,
  onAdd,
  onDuplicate,
  onDelete,
  onRename,
}: {
  shots: readonly DesignerShot[];
  activeShotId: string | null;
  atLimit: boolean;
  onSelect: (shotId: string) => void;
  onAdd: () => void;
  onDuplicate: () => void;
  onDelete: () => void;
  onRename: (label: string) => void;
}) {
  const active = shots.find((shot) => shot.id === activeShotId);
  return (
    <div className="flex min-w-max items-center gap-1 border-b bg-neutral-800 px-2 py-1.5 text-white" aria-label="Drawing sheets">
      <span className="px-2 text-[10px] font-bold uppercase tracking-[0.15em] text-neutral-400">Sheets</span>
      {shots.map((shot, index) => (
        <button
          key={shot.id}
          type="button"
          aria-current={shot.id === activeShotId ? "page" : undefined}
          onClick={() => onSelect(shot.id)}
          className={cn(
            "h-8 min-w-24 border px-3 text-xs font-semibold transition-[color,background-color,border-color] duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400 motion-reduce:transition-none",
            shot.id === activeShotId
              ? "border-amber-400 bg-amber-400 text-black"
              : "border-white/15 bg-neutral-900 text-neutral-300 hover:border-white/30 hover:text-white",
          )}
        >
          {shot.sheet?.label || `Sheet ${index + 1}`}
        </button>
      ))}
      <Button type="button" size="icon-sm" variant="ghost" disabled={atLimit} onClick={onAdd} aria-label="Add drawing sheet" className="text-white hover:bg-white/10 hover:text-white"><Plus aria-hidden="true" /></Button>
      <Button type="button" size="icon-sm" variant="ghost" disabled={!active || atLimit} onClick={onDuplicate} aria-label="Duplicate active drawing sheet" className="text-white hover:bg-white/10 hover:text-white"><Copy aria-hidden="true" /></Button>
      <Button type="button" size="icon-sm" variant="ghost" disabled={shots.length <= 1} onClick={onDelete} aria-label="Delete active drawing sheet" className="text-white hover:bg-white/10 hover:text-white"><Trash2 aria-hidden="true" /></Button>
      {active ? (
        <label className="ml-2 flex items-center gap-2 text-[10px] font-semibold uppercase tracking-wide text-neutral-400">
          Label
          <input
            value={active.sheet?.label ?? ""}
            maxLength={120}
            onChange={(event) => onRename(event.target.value)}
            className="h-8 w-40 rounded border border-white/15 bg-neutral-950 px-2 text-xs normal-case tracking-normal text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
          />
        </label>
      ) : null}
    </div>
  );
}
