"use client";

import { Command } from "cmdk";
import { Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useMemo, useState } from "react";

import { Dialog, DialogContent } from "@/components/ui/dialog";

import { appNavSections, isNavItemVisible } from "./app-nav";

interface CommandPaletteProps {
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}

export function CommandPalette({
  open: controlledOpen,
  onOpenChange,
}: CommandPaletteProps = {}) {
  const [internalOpen, setInternalOpen] = useState(false);
  const router = useRouter();

  const commandGroups = useMemo(
    () =>
      appNavSections
        .filter((section) => !section.devOnly || process.env.NODE_ENV !== "production")
        .map((section) => ({
          title: section.title,
          items: section.items.filter(
            (item) => item.commandPalette && isNavItemVisible(item)
          ),
        }))
        .filter((section) => section.items.length > 0),
    []
  );

  const isControlled = controlledOpen !== undefined;
  const open = isControlled ? controlledOpen : internalOpen;

  const setOpen = useCallback(
    (value: boolean) => {
      if (!isControlled) setInternalOpen(value);
      onOpenChange?.(value);
    },
    [isControlled, onOpenChange]
  );

  const handleSelect = (href: string) => {
    router.push(href);
    setOpen(false);
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="max-w-lg overflow-hidden border-primary/20 bg-card/95 p-0 shadow-2xl backdrop-blur-xl">
        <Command className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-muted-foreground [&_[cmdk-group]:not([hidden])_~[cmdk-group]]:pt-0 [&_[cmdk-group]]:px-2 [&_[cmdk-input-wrapper]_svg]:size-5 [&_[cmdk-input]]:h-12 [&_[cmdk-item]]:px-2 [&_[cmdk-item]]:py-3 [&_[cmdk-item]_svg]:size-5">
          <div className="flex items-center border-b border-border px-3">
            <Search className="mr-2 size-4 shrink-0 text-muted-foreground" />
            <Command.Input
              placeholder="Search pages, contacts, campaigns..."
              className="flex h-12 w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed disabled:opacity-50"
            />
          </div>
          <Command.List className="app-scrollbar max-h-80 overflow-y-auto overflow-x-hidden p-2">
            <Command.Empty className="py-6 text-center text-sm text-muted-foreground">
              No results found.
            </Command.Empty>
            {commandGroups.map((group) => (
              <Command.Group key={group.title} heading={group.title}>
                {group.items.map((item) => {
                  const Icon = item.icon;

                  return (
                    <Command.Item
                      key={item.url}
                      value={item.title}
                      onSelect={() => handleSelect(item.url)}
                      className="flex cursor-pointer items-center gap-3 rounded-md px-2 py-2 text-sm transition-colors hover:bg-accent aria-selected:bg-accent"
                    >
                      <div className="flex size-7 items-center justify-center rounded-md bg-primary/10">
                        <Icon className="size-4 text-primary" />
                      </div>
                      {item.title}
                    </Command.Item>
                  );
                })}
              </Command.Group>
            ))}
          </Command.List>
          <div className="flex items-center gap-2 border-t border-border px-3 py-2 text-xs text-muted-foreground">
            <kbd className="rounded border border-border bg-muted px-1.5 py-0.5 font-mono text-[10px]">
              ↑↓
            </kbd>
            <span>navigate</span>
            <kbd className="rounded border border-border bg-muted px-1.5 py-0.5 font-mono text-[10px]">
              ↵
            </kbd>
            <span>select</span>
            <kbd className="rounded border border-border bg-muted px-1.5 py-0.5 font-mono text-[10px]">
              esc
            </kbd>
            <span>close</span>
            <div className="ml-auto flex items-center gap-1">
              <kbd className="rounded border border-border bg-muted px-1.5 py-0.5 font-mono text-[10px]">
                ⌘K
              </kbd>
            </div>
          </div>
        </Command>
      </DialogContent>
    </Dialog>
  );
}
