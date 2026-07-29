import { useEffect, useState } from "react"

const MOBILE_BREAKPOINT = 768
/**
 * Below this width the three-column conversation console cannot hold a readable
 * message column next to both rails (256px app nav + 2 rails leaves < 400px),
 * so the rails move into slide-overs instead of squeezing the conversation.
 */
const CONSOLE_BREAKPOINT = 1280

/**
 * Subscribe to a media query. Resolves synchronously on the client (so a
 * desktop never flashes the narrow layout) and reports `false` during SSR,
 * matching the `useIsMobile` convention above.
 */
export function useMediaQuery(query: string) {
  const [matches, setMatches] = useState<boolean | undefined>(() =>
    typeof window === "undefined" ? undefined : window.matchMedia(query).matches
  )

  useEffect(() => {
    const mql = window.matchMedia(query)
    const onChange = () => setMatches(mql.matches)
    onChange()
    mql.addEventListener("change", onChange)
    return () => mql.removeEventListener("change", onChange)
  }, [query])

  return !!matches
}

export function useIsMobile() {
  const [isMobile, setIsMobile] = useState<boolean | undefined>(() =>
    typeof window === "undefined" ? undefined : window.innerWidth < MOBILE_BREAKPOINT
  )

  useEffect(() => {
    const mql = window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT - 1}px)`)
    const onChange = () => {
      setIsMobile(window.innerWidth < MOBILE_BREAKPOINT)
    }
    mql.addEventListener("change", onChange)
    return () => mql.removeEventListener("change", onChange)
  }, [])

  return !!isMobile
}

/**
 * True when the viewport is too narrow for the side-by-side conversation
 * console (mobile phones through small laptops).
 */
export function useIsCompactConsole() {
  return !useMediaQuery(`(min-width: ${CONSOLE_BREAKPOINT}px)`)
}
