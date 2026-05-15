"use client";

import dynamic from "next/dynamic";

/**
 * Lazy-loaded Calendar wrapper.
 *
 * `react-day-picker` is ~50KB gzipped and only ever surfaces inside dialogs or
 * popovers (appointment scheduling, nudge snooze). Importing it through this
 * shim keeps it out of the initial bundle of every page that pulls in those
 * dialogs.
 *
 * Use this everywhere instead of `@/components/ui/calendar` directly.
 */
export const Calendar = dynamic(
  () => import("@/components/ui/calendar").then((m) => m.Calendar),
  {
    ssr: false,
    loading: () => (
      <div className="h-[300px] w-[280px] animate-pulse rounded-md bg-muted/30" />
    ),
  },
);
