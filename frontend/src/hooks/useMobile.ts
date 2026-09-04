import { useCallback, useSyncExternalStore } from "react"

const MOBILE_BREAKPOINT = 768
const NAVIGATION_BREAKPOINT = 1280
const IPAD_LANDSCAPE_MAX_WIDTH = 1366
const COMPACT_NAVIGATION_QUERY =
  `(max-width: ${NAVIGATION_BREAKPOINT - 1}px), ` +
  `(hover: none) and (pointer: coarse) and (max-width: ${IPAD_LANDSCAPE_MAX_WIDTH}px)`

/**
 * Subscribe to a media query without rendering different server and hydration
 * trees. React uses the server snapshot for the hydration pass, then reads the
 * real viewport before the browser paints the settled client layout.
 */
export function useMediaQuery(query: string) {
  const subscribe = useCallback(
    (onStoreChange: () => void) => {
      const mediaQuery = window.matchMedia(query)
      mediaQuery.addEventListener("change", onStoreChange)
      return () => mediaQuery.removeEventListener("change", onStoreChange)
    },
    [query]
  )
  const getSnapshot = useCallback(() => window.matchMedia(query).matches, [query])

  return useSyncExternalStore(subscribe, getSnapshot, () => false)
}

export function useIsMobile() {
  return useMediaQuery(`(max-width: ${MOBILE_BREAKPOINT - 1}px)`)
}

/**
 * Use overlay navigation on compact windows and touch-first iPads in landscape,
 * preserving the full page width instead of permanently spending 256px on navigation.
 */
export function useIsCompactNavigation() {
  return useMediaQuery(COMPACT_NAVIGATION_QUERY)
}

/**
 * Below this width the three-column conversation console cannot hold a readable
 * message column next to both rails (256px app nav + 2 rails leaves < 400px),
 * so the rails move into slide-overs instead of squeezing the conversation.
 */
const CONSOLE_BREAKPOINT = 1280

export function useIsCompactConsole() {
  return !useMediaQuery(`(min-width: ${CONSOLE_BREAKPOINT}px)`)
}
