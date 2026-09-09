/**
 * In-memory record of recent client-side failures, so the CRM Assistant can be
 * handed real evidence when someone asks "why is this page broken?" — a
 * screenshot shows an empty table, this shows the 500 that emptied it.
 *
 * Deliberately records *shapes only*: method, path, status, error message.
 * Never bodies, headers, or query strings — this text is pasted into an
 * assistant prompt and forwarded to the model provider, so anything captured
 * here leaves the browser.
 */

const MAX_ENTRIES = 8;
const MAX_DETAIL_CHARS = 200;

export interface DiagnosticEntry {
  at: number;
  source: "network" | "script";
  detail: string;
}

let entries: DiagnosticEntry[] = [];

/**
 * Path component only. Query strings carry invite tokens, share tokens and
 * search terms, so they must never reach the prompt.
 */
export function safePath(url: string): string {
  if (!url) return "unknown";
  try {
    return new URL(url, "http://local.invalid").pathname || "unknown";
  } catch {
    return "unknown";
  }
}

export function recordDiagnostic(source: DiagnosticEntry["source"], detail: string): void {
  const trimmed = detail.trim().slice(0, MAX_DETAIL_CHARS);
  if (!trimmed) return;
  entries = [...entries, { at: Date.now(), source, detail: trimmed }].slice(-MAX_ENTRIES);
}

export function getDiagnostics(): DiagnosticEntry[] {
  return entries;
}

export function clearDiagnostics(): void {
  entries = [];
}

/** Record a failed API call. Auth probes are excluded — a signed-out 401 is routine. */
export function recordApiFailure(params: {
  method?: string;
  url?: string;
  status?: number;
  message?: string;
}): void {
  const path = safePath(params.url ?? "");
  if (path.startsWith("/api/v1/auth/")) return;
  const method = (params.method ?? "get").toUpperCase();
  const outcome = params.status ? `${params.status}` : (params.message ?? "network error");
  recordDiagnostic("network", `${method} ${path} → ${outcome}`);
}

let listenersInstalled = false;

/** Capture uncaught errors and rejected promises. Idempotent; browser-only. */
export function installDiagnosticsListeners(): void {
  if (listenersInstalled || typeof window === "undefined") return;
  listenersInstalled = true;

  window.addEventListener("error", (event) => {
    const where = event.filename ? ` (${safePath(event.filename)}:${event.lineno})` : "";
    recordDiagnostic("script", `${event.message}${where}`);
  });

  window.addEventListener("unhandledrejection", (event) => {
    const reason = event.reason;
    const message = reason instanceof Error ? reason.message : String(reason ?? "unknown");
    recordDiagnostic("script", `Unhandled rejection: ${message}`);
  });
}

/** Recent failures as prompt-ready lines, oldest first. Empty string when clean. */
export function describeDiagnostics(now: number = Date.now()): string {
  if (entries.length === 0) return "";
  const lines = entries.map((entry) => {
    const secondsAgo = Math.max(0, Math.round((now - entry.at) / 1000));
    return `- ${entry.source}: ${entry.detail} (${secondsAgo}s ago)`;
  });
  return `Recent client-side errors:\n${lines.join("\n")}`;
}

/**
 * Starting prompt for a screen capture. Rendered into the composer rather than
 * sent silently, so the user can read (and edit) every word that leaves the app.
 */
export function buildScreenTroubleshootPrompt(pathname: string, now?: number): string {
  const parts = [
    "Troubleshoot what I'm looking at in this screenshot. Tell me what's wrong and how to fix it.",
    `Page: ${pathname || "unknown"}`,
  ];
  const diagnostics = describeDiagnostics(now);
  if (diagnostics) parts.push(diagnostics);
  return parts.join("\n\n");
}
