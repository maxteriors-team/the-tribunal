export const TEXT_RESPONSE_MIN_DELAY_MS = 22_000;
export const TEXT_RESPONSE_DEFAULT_DELAY_MS = 30_000;
export const TEXT_RESPONSE_MAX_DELAY_MS = 180_000;
export const TEXT_RESPONSE_DELAY_STEP_MS = 1_000;

export function clampTextResponseDelayMs(value: number | null | undefined): number {
  if (value == null || Number.isNaN(value)) {
    return TEXT_RESPONSE_DEFAULT_DELAY_MS;
  }

  return Math.min(
    TEXT_RESPONSE_MAX_DELAY_MS,
    Math.max(TEXT_RESPONSE_MIN_DELAY_MS, value)
  );
}

export function formatTextResponseDelay(ms: number): string {
  const totalSeconds = Math.round(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;

  if (minutes === 0) {
    return `${seconds}s`;
  }

  if (seconds === 0) {
    return `${minutes}m`;
  }

  return `${minutes}m ${seconds}s`;
}
