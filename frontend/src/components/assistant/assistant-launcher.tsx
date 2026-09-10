"use client";

/**
 * The assistant as a chat widget, reachable from wherever the operator already is.
 *
 * `/assistant` is a whole page, so asking it anything means leaving the screen
 * you were working on and finding your place again afterwards. That cost is paid
 * on every question, which is enough to stop people asking. This is the same
 * assistant in a floating card over the current screen.
 *
 * Three states, and the difference between two of them matters:
 *
 * - **closed** — just the bubble. The chat is unmounted, so nothing polls.
 * - **minimised** — back to the bubble, but the chat stays mounted and keeps a
 *   half-typed question and the streaming reply alive. That is the whole point
 *   of minimise as distinct from close.
 * - **open** — the card, at normal or expanded size.
 *
 * Deliberately mounts the *same* {@link AssistantChat} the full page uses rather
 * than a trimmed-down copy: two chat surfaces would drift and this one would
 * quietly become the worse one. Conversations are server-side and keyed by
 * workspace, so a thread started here continues on the page and back.
 */

import { Maximize2, MessageCircleQuestion, Minimize2, Minus, X } from "lucide-react";
import dynamic from "next/dynamic";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { PageLoadingState } from "@/components/ui/page-state";
import { cn } from "@/lib/utils";
import { useWorkspace } from "@/providers/workspace-provider";

// Keeps the assistant runtime out of the initial bundle of every page this is
// mounted on. `ssr: false` because the chat reads browser-only state.
const AssistantChat = dynamic(
  () => import("@/components/assistant/assistant-chat").then((m) => m.AssistantChat),
  { ssr: false, loading: () => <PageLoadingState className="min-h-0 flex-1" /> },
);

export function AssistantLauncher() {
  // `mounted` outlives `open` so minimising keeps the conversation alive.
  const [mounted, setMounted] = useState(false);
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const { currentWorkspace } = useWorkspace();

  const openWidget = () => {
    setMounted(true);
    setOpen(true);
  };

  // ⌘/ (Ctrl+/) toggles it. ⌘K is already the command palette, and "/" is the
  // near-universal "ask something" key.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "/" && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        if (open) setOpen(false);
        else openWidget();
      }
      // Escape minimises rather than closes, so it never costs a half-typed
      // question — the same reason the widget has no click-outside dismiss.
      if (event.key === "Escape" && open) setOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open]);

  // The assistant acts inside a workspace, so before one is chosen the bubble
  // would open a widget that cannot answer anything.
  if (!currentWorkspace) return null;

  return (
    <>
      {!open ? (
        <Button
          type="button"
          size="icon"
          onClick={openWidget}
          aria-label="Ask the CRM assistant"
          title="Ask the CRM assistant (⌘/)"
          className="fixed bottom-5 right-5 z-40 size-12 rounded-full shadow-lg print:hidden"
        >
          <MessageCircleQuestion className="size-5" />
        </Button>
      ) : null}

      {mounted ? (
        <div
          // Hidden, not unmounted, while minimised: that is what preserves the
          // draft and any in-flight reply.
          hidden={!open}
          data-testid="assistant-widget"
          role="dialog"
          aria-label="CRM Assistant"
          className={cn(
            "fixed bottom-5 right-5 z-40 flex flex-col overflow-hidden rounded-xl border bg-background shadow-2xl print:hidden",
            // Never taller than the viewport, and full-width on a phone where a
            // floating card would otherwise hang off the screen.
            "max-h-[calc(100vh-2.5rem)] max-w-[calc(100vw-2.5rem)]",
            expanded ? "h-[46rem] w-[52rem]" : "h-[36rem] w-[26rem]",
          )}
        >
          <header className="flex shrink-0 items-center gap-1 border-b px-3 py-2">
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-semibold">CRM Assistant</p>
              <p className="truncate text-xs text-muted-foreground">
                Ask without leaving this page
              </p>
            </div>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="size-8"
              onClick={() => setExpanded((prev) => !prev)}
              aria-label={expanded ? "Shrink assistant" : "Expand assistant"}
              aria-pressed={expanded}
            >
              {expanded ? <Minimize2 className="size-4" /> : <Maximize2 className="size-4" />}
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="size-8"
              onClick={() => setOpen(false)}
              aria-label="Minimize assistant"
            >
              <Minus className="size-4" />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="size-8"
              onClick={() => {
                setOpen(false);
                // Unmount: closing is the deliberate "I'm done" action, and it
                // must stop the chat's polling rather than hide it forever.
                setMounted(false);
                setExpanded(false);
              }}
              aria-label="Close assistant"
            >
              <X className="size-4" />
            </Button>
          </header>

          {/* The saved-chats rail is hidden here: it is a fixed 288px sized for a
              full page and would leave the composer too narrow to type in.
              Earlier chats stay on the full Assistant page. */}
          <AssistantChat className="min-h-0 flex-1" showConversationList={false} />
        </div>
      ) : null}
    </>
  );
}
