const AUTO_REDIRECT_PREFIX = "sales_rep_onboarding_autoredirected";
const COMPLETED_PREFIX = "sales_rep_onboarding_completed";

// Keeps first-run behavior stable for this tab when browser storage is unavailable.
const inMemoryFlags = new Set<string>();

function key(prefix: string, userId: number, workspaceId: string): string {
  return `${prefix}:${userId}:${workspaceId}`;
}

function hasFlag(flag: string): boolean {
  if (typeof window === "undefined") return false;
  if (inMemoryFlags.has(flag)) return true;

  try {
    return localStorage.getItem(flag) === "true";
  } catch {
    return false;
  }
}

function markFlag(flag: string): void {
  if (typeof window === "undefined") return;
  inMemoryFlags.add(flag);

  try {
    localStorage.setItem(flag, "true");
  } catch {
    // The in-memory fallback prevents redirect loops for this open tab.
  }
}

export function hasAutoRedirectedToSalesRepOnboarding(
  userId: number,
  workspaceId: string,
): boolean {
  return hasFlag(key(AUTO_REDIRECT_PREFIX, userId, workspaceId));
}

export function markAutoRedirectedToSalesRepOnboarding(userId: number, workspaceId: string): void {
  markFlag(key(AUTO_REDIRECT_PREFIX, userId, workspaceId));
}

export function hasCompletedSalesRepOnboarding(userId: number, workspaceId: string): boolean {
  return hasFlag(key(COMPLETED_PREFIX, userId, workspaceId));
}

export function markSalesRepOnboardingCompleted(userId: number, workspaceId: string): void {
  markFlag(key(COMPLETED_PREFIX, userId, workspaceId));
}
