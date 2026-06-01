import { useEffect, useState } from "react";

import { resolveThemeOption } from "@/lib/embed/theme";

import type { AgentConfig, ResolvedTheme, ThemeOption } from "./_types";

/**
 * Resolves a `"light" | "dark" | "auto"` preference into a concrete
 * `"light" | "dark"` value, listening to system-preference changes for `auto`.
 */
export function useResolvedTheme(theme: ThemeOption): ResolvedTheme {
  const [resolved, setResolved] = useState<ResolvedTheme>("light");

  /* eslint-disable react-hooks/set-state-in-effect -- Syncing with system color-scheme media query. */
  useEffect(() => {
    if (theme === "auto") {
      const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
      setResolved(resolveThemeOption(theme, mediaQuery.matches));
      const handler = (e: MediaQueryListEvent) =>
        setResolved(resolveThemeOption(theme, e.matches));
      mediaQuery.addEventListener("change", handler);
      return () => mediaQuery.removeEventListener("change", handler);
    }
    setResolved(resolveThemeOption(theme, false));
    return undefined;
  }, [theme]);
  /* eslint-enable react-hooks/set-state-in-effect */

  return resolved;
}

export interface UseAgentConfigResult {
  config: AgentConfig | null;
  error: string | null;
  setError: (err: string | null) => void;
}

/**
 * Fetches the public agent config keyed by `publicId`. The same shape is
 * consumed by every embed surface (widget, chat, fullpage, both).
 */
export function useAgentConfig(publicId: string): UseAgentConfigResult {
  const [config, setConfig] = useState<AgentConfig | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!publicId) return;
    let cancelled = false;

    async function fetchConfig() {
      try {
        const res = await fetch(`/api/v1/p/embed/${publicId}/config`, {
          headers: { Origin: window.location.origin },
        });
        if (!res.ok) {
          const data = await res.json();
          throw new Error((data.detail as string) ?? "Failed to load agent");
        }
        const data = (await res.json()) as AgentConfig;
        if (!cancelled) setConfig(data);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load agent");
        }
      }
    }

    void fetchConfig();
    return () => {
      cancelled = true;
    };
  }, [publicId]);

  return { config, error, setError };
}
