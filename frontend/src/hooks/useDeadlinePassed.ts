"use client";

import { useCallback, useSyncExternalStore } from "react";

/**
 * Whether `deadline` is in the past, re-rendering exactly when it passes.
 *
 * Reading the clock during render is impure and would also leave a composer
 * open on an already-closed thread until something else happened to re-render.
 * The timer fires once, on the deadline itself.
 */
export function useDeadlinePassed(deadline: string | null | undefined): boolean {
  const at = deadline ? new Date(deadline).getTime() : null;
  const valid = at !== null && !Number.isNaN(at);

  const subscribe = useCallback(
    (onChange: () => void) => {
      const remaining = valid ? at - Date.now() : -1;
      if (!valid || remaining <= 0) return () => {};
      // Clamped: setTimeout overflows past ~24.9 days and would fire at once.
      const timer = setTimeout(onChange, Math.min(remaining, 2_147_483_647));
      return () => clearTimeout(timer);
    },
    [at, valid],
  );

  const getSnapshot = useCallback(() => valid && at <= Date.now(), [at, valid]);

  // Server render: nothing has expired yet, so the composer starts available.
  return useSyncExternalStore(subscribe, getSnapshot, () => false);
}
