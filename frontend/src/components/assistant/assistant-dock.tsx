"use client";

import { Maximize2, Minimize2, Sparkles, SquareArrowOutUpRight, X } from "lucide-react";
import Link from "next/link";
import { Suspense, useEffect, useRef, useState } from "react";

import { AssistantChat } from "@/components/assistant/assistant-chat";
import { Button } from "@/components/ui/button";
import { PageLoadingState } from "@/components/ui/page-state";
import { installDiagnosticsListeners } from "@/lib/assistant/diagnostics";
import { cn } from "@/lib/utils";

const OPEN_STORAGE_KEY = "assistant-dock:open";

/**
 * Floating CRM Assistant window: a launcher pinned bottom-right that opens the
 * full assistant chat (tools, approvals and all) over any page.
 *
 * Once opened the chat stays mounted and is only hidden, so collapsing the
 * window never aborts an in-flight assistant run.
 */
export function AssistantDock() {
  // Mounted with `ssr: false`, so reading storage during init is safe and
  // avoids a closed-then-open flash on every navigation.
  const [open, setOpen] = useState(
    () => window.localStorage.getItem(OPEN_STORAGE_KEY) === "1",
  );
  // "Has been opened at least once" — the chat mounts lazily and then stays.
  const [mounted, setMounted] = useState(open);
  const [expanded, setExpanded] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);
  const launcherRef = useRef<HTMLButtonElement>(null);

  // Collect errors from first paint, not from first open — by the time someone
  // asks the assistant what broke, the failure has already happened.
  useEffect(() => {
    installDiagnosticsListeners();
  }, []);

  // Every route renders its own AppSidebar, so this remounts on navigation;
  // persisting the flag keeps an open window following you across pages.
  useEffect(() => {
    window.localStorage.setItem(OPEN_STORAGE_KEY, open ? "1" : "0");
  }, [open]);

  // Land the caret in the message box on open, so you can type (and press Esc)
  // without hunting for the composer; hand focus back to the launcher on close.
  const openedOnceRef = useRef(false);
  useEffect(() => {
    if (!open) {
      if (openedOnceRef.current) launcherRef.current?.focus();
      return;
    }
    openedOnceRef.current = true;
    const panel = panelRef.current;
    if (panel) (panel.querySelector("textarea") ?? panel).focus();
  }, [open]);

  // Esc closes the window. Bound natively rather than as a JSX handler: a
  // `role="dialog"` container is non-interactive, so React key props on it are
  // an a11y smell. Nested Radix dialogs portal out, so their own Esc never
  // reaches this node.
  useEffect(() => {
    const panel = panelRef.current;
    if (!panel || !open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.stopPropagation();
      setOpen(false);
    };
    panel.addEventListener("keydown", onKeyDown);
    return () => panel.removeEventListener("keydown", onKeyDown);
  }, [open]);

  const openDock = () => {
    setMounted(true);
    setOpen(true);
  };

  return (
    <>
      {!open ? (
        <Button
          ref={launcherRef}
          type="button"
          size="icon"
          onClick={openDock}
          aria-label="Open CRM Assistant"
          className="fixed bottom-4 right-4 z-50 size-12 rounded-full shadow-lg sm:bottom-6 sm:right-6"
        >
          <Sparkles className="size-5" />
        </Button>
      ) : null}

      {mounted ? (
        <div
          ref={panelRef}
          role="dialog"
          aria-label="CRM Assistant"
          tabIndex={-1}
          // Collapsed the window is hidden but still mounted, so take it out of
          // the tab order and the accessibility tree too.
          inert={!open}
          aria-hidden={!open}
          className={cn(
            "fixed bottom-2 right-2 z-50 flex flex-col overflow-hidden rounded-xl border border-border bg-background shadow-2xl",
            "left-2 h-[min(32rem,calc(100svh-1rem))] sm:left-auto sm:bottom-4 sm:right-4",
            expanded
              ? "sm:h-[min(46rem,calc(100svh-2rem))] sm:w-[min(60rem,calc(100vw-2rem))]"
              : "sm:h-[min(36rem,calc(100svh-2rem))] sm:w-[min(26rem,calc(100vw-2rem))]",
            open ? "flex" : "hidden",
          )}
        >
          <div className="flex shrink-0 items-center gap-2 border-b px-3 py-2">
            <Sparkles className="size-4 text-primary" />
            <p className="min-w-0 flex-1 truncate text-sm font-semibold">CRM Assistant</p>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="hidden size-8 sm:inline-flex"
              onClick={() => setExpanded((value) => !value)}
              aria-label={expanded ? "Shrink assistant window" : "Expand assistant window"}
            >
              {expanded ? <Minimize2 className="size-4" /> : <Maximize2 className="size-4" />}
            </Button>
            <Button type="button" variant="ghost" size="icon" className="size-8" asChild>
              <Link href="/assistant" aria-label="Open assistant full page">
                <SquareArrowOutUpRight className="size-4" />
              </Link>
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="size-8"
              onClick={() => setOpen(false)}
              aria-label="Close CRM Assistant"
            >
              <X className="size-4" />
            </Button>
          </div>

          {/* Suspense: AssistantChat reads useSearchParams. */}
          <Suspense fallback={<PageLoadingState className="min-h-0 flex-1" />}>
            <AssistantChat compact className="min-h-0 flex-1" />
          </Suspense>
        </div>
      ) : null}
    </>
  );
}
