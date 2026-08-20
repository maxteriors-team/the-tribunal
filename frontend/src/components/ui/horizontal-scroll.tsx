"use client";

/* eslint-disable jsx-a11y/no-noninteractive-tabindex -- Horizontal overflow must remain keyboard-scrollable in Safari. */

import { ChevronLeft, ChevronRight } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type ComponentProps } from "react";

import { cn } from "@/lib/utils";

type HorizontalScrollProps = ComponentProps<"div"> & {
  activeKey?: string | number;
  viewportClassName?: string;
};

export function HorizontalScroll({
  activeKey,
  children,
  className,
  onScroll,
  viewportClassName,
  ...props
}: HorizontalScrollProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [scrollEdges, setScrollEdges] = useState({ left: false, right: false });

  const updateScrollEdges = useCallback(() => {
    const viewport = scrollRef.current;
    if (!viewport) return;

    setScrollEdges({
      left: viewport.scrollLeft > 1,
      right: viewport.scrollLeft + viewport.clientWidth < viewport.scrollWidth - 1,
    });
  }, []);

  useEffect(() => {
    const viewport = scrollRef.current;
    if (!viewport) return;

    const frame = requestAnimationFrame(updateScrollEdges);
    const resizeObserver = new ResizeObserver(updateScrollEdges);
    resizeObserver.observe(viewport);

    return () => {
      cancelAnimationFrame(frame);
      resizeObserver.disconnect();
    };
  }, [children, updateScrollEdges]);

  useEffect(() => {
    if (activeKey === undefined) return;

    const activeItem = scrollRef.current?.querySelector<HTMLElement>(
      '[aria-current="step"], [aria-selected="true"], [aria-pressed="true"]',
    );
    activeItem?.scrollIntoView({ block: "nearest", inline: "nearest" });
    requestAnimationFrame(updateScrollEdges);
  }, [activeKey, updateScrollEdges]);

  return (
    <div
      data-slot="horizontal-scroll-root"
      className={cn("relative min-w-0 max-w-full", className)}
    >
      <div
        ref={scrollRef}
        data-slot="horizontal-scroll"
        data-scroll-left={scrollEdges.left || undefined}
        data-scroll-right={scrollEdges.right || undefined}
        role="region"
        tabIndex={0}
        className={cn(
          "app-scrollbar min-w-0 max-w-full overflow-x-auto overscroll-x-contain pb-2 [scrollbar-gutter:stable] focus-visible:rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
          viewportClassName,
        )}
        onScroll={(event) => {
          updateScrollEdges();
          onScroll?.(event);
        }}
        {...props}
      >
        {children}
      </div>
      {scrollEdges.left ? (
        <div
          data-slot="horizontal-scroll-cue"
          className="pointer-events-none absolute inset-y-2 left-0 flex w-10 items-center bg-gradient-to-r from-background via-background/90 to-transparent"
          aria-hidden="true"
        >
          <ChevronLeft className="size-4" />
        </div>
      ) : null}
      {scrollEdges.right ? (
        <div
          data-slot="horizontal-scroll-cue"
          className="pointer-events-none absolute inset-y-2 right-0 flex w-10 items-center justify-end bg-gradient-to-l from-background via-background/90 to-transparent"
          aria-hidden="true"
        >
          <ChevronRight className="size-4" />
        </div>
      ) : null}
    </div>
  );
}
