import { useSyncExternalStore } from "react";

const subscribe = () => () => {};

/**
 * Returns `false` during SSR and the first (hydration) render, then `true`.
 *
 * Gate browser-only UI — theme, localStorage, window size — behind this so the
 * server and client emit identical markup on the hydration pass. Reading that
 * state directly during render makes React discard and re-render the tree with
 * a hydration mismatch.
 */
export function useIsMounted() {
  return useSyncExternalStore(
    subscribe,
    () => true,
    () => false
  );
}
