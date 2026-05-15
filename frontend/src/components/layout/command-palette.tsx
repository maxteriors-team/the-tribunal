"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Command } from "cmdk";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import {
  LayoutDashboard, Users, Megaphone, Phone, Bot, Settings,
  Calendar, Zap, Gift, Lightbulb, MapPin, Sparkles, Search,
} from "lucide-react";

const navItems = [
  { label: "Dashboard", href: "/dashboard", icon: LayoutDashboard, group: "Navigate" },
  { label: "Contacts", href: "/contacts", icon: Users, group: "Navigate" },
  { label: "Campaigns", href: "/campaigns", icon: Megaphone, group: "Navigate" },
  { label: "Calls", href: "/calls", icon: Phone, group: "Navigate" },
  { label: "AI Agents", href: "/agents", icon: Bot, group: "Navigate" },
  { label: "AI Suggestions", href: "/suggestions", icon: Lightbulb, group: "Navigate" },
  { label: "Automations", href: "/automations", icon: Zap, group: "Navigate" },
  { label: "Offers", href: "/offers", icon: Gift, group: "Navigate" },
  { label: "Calendar", href: "/calendar", icon: Calendar, group: "Navigate" },
  { label: "Find Leads", href: "/find-leads", icon: MapPin, group: "Navigate" },
  { label: "Find Leads AI", href: "/find-leads-ai", icon: Sparkles, group: "Navigate" },
  { label: "Settings", href: "/settings", icon: Settings, group: "Navigate" },
];

interface CommandPaletteProps {
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}

export function CommandPalette({ open: controlledOpen, onOpenChange }: CommandPaletteProps = {}) {
  const [internalOpen, setInternalOpen] = React.useState(false);
  const router = useRouter();

  const isControlled = controlledOpen !== undefined;
  const open = isControlled ? controlledOpen : internalOpen;

  const setOpen = React.useCallback((value: boolean) => {
    if (!isControlled) setInternalOpen(value);
    onOpenChange?.(value);
  }, [isControlled, onOpenChange]);

  const handleSelect = (href: string) => {
    router.push(href);
    setOpen(false);
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="overflow-hidden p-0 shadow-2xl max-w-lg bg-card/95 backdrop-blur-xl border-primary/20">
        <Command className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-muted-foreground [&_[cmdk-group]:not([hidden])_~[cmdk-group]]:pt-0 [&_[cmdk-group]]:px-2 [&_[cmdk-input-wrapper]_svg]:size-5 [&_[cmdk-input]]:h-12 [&_[cmdk-item]]:px-2 [&_[cmdk-item]]:py-3 [&_[cmdk-item]_svg]:size-5">
          <div className="flex items-center border-b border-border px-3">
            <Search className="mr-2 size-4 shrink-0 text-muted-foreground" />
            <Command.Input
              placeholder="Search pages, contacts, campaigns..."
              className="flex h-12 w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed disabled:opacity-50"
            />
          </div>
          <Command.List className="max-h-80 overflow-y-auto overflow-x-hidden p-2">
            <Command.Empty className="py-6 text-center text-sm text-muted-foreground">
              No results found.
            </Command.Empty>
            <Command.Group heading="Navigate">
              {navItems.map((item) => (
                <Command.Item
                  key={item.href}
                  value={item.label}
                  onSelect={() => handleSelect(item.href)}
                  className="flex items-center gap-3 rounded-md px-2 py-2 text-sm cursor-pointer hover:bg-accent aria-selected:bg-accent transition-colors"
                >
                  <div className="flex size-7 items-center justify-center rounded-md bg-primary/10">
                    <item.icon className="size-4 text-primary" />
                  </div>
                  {item.label}
                </Command.Item>
              ))}
            </Command.Group>
          </Command.List>
          <div className="border-t border-border px-3 py-2 flex items-center gap-2 text-xs text-muted-foreground">
            <kbd className="rounded border border-border bg-muted px-1.5 py-0.5 font-mono text-[10px]">↑↓</kbd>
            <span>navigate</span>
            <kbd className="rounded border border-border bg-muted px-1.5 py-0.5 font-mono text-[10px]">↵</kbd>
            <span>select</span>
            <kbd className="rounded border border-border bg-muted px-1.5 py-0.5 font-mono text-[10px]">esc</kbd>
            <span>close</span>
            <div className="ml-auto flex items-center gap-1">
              <kbd className="rounded border border-border bg-muted px-1.5 py-0.5 font-mono text-[10px]">⌘K</kbd>
            </div>
          </div>
        </Command>
      </DialogContent>
    </Dialog>
  );
}
