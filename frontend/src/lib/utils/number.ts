// Number formatting helpers built on Intl.NumberFormat. Centralised so locale
// and rounding rules stay consistent across the app.

const DEFAULT_LOCALE = "en-US";

/** Decimal-grouped integer/float, e.g. 1234567.89 -> "1,234,567.89". */
export function formatNumber(value: number): string {
  if (!Number.isFinite(value)) return "—";
  return new Intl.NumberFormat(DEFAULT_LOCALE).format(value);
}

/** Currency, e.g. 1234.5 -> "$1,234.50". Defaults to USD. */
export function formatCurrency(value: number, currency: string = "USD"): string {
  if (!Number.isFinite(value)) return "—";
  return new Intl.NumberFormat(DEFAULT_LOCALE, {
    style: "currency",
    currency,
  }).format(value);
}

/**
 * Percent of a 0..1 fraction, e.g. 0.1234 -> "12.34%". Pass already-multiplied
 * values divided by 100 if your source is whole-number percents.
 */
export function formatPercent(value: number): string {
  if (!Number.isFinite(value)) return "—";
  return new Intl.NumberFormat(DEFAULT_LOCALE, {
    style: "percent",
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  }).format(value);
}
