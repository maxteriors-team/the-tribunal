import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Options for {@link useDebouncedSearch}.
 */
export interface UseDebouncedSearchOptions {
  /** Debounce delay in milliseconds. Defaults to 300ms. */
  delay?: number;
  /** Initial input value. Defaults to an empty string. */
  initialValue?: string;
  /**
   * Called with the debounced value after the user stops typing for `delay`.
   * Useful for syncing into an external store (e.g. zustand) or analytics.
   */
  onDebouncedChange?: (value: string) => void;
}

/**
 * Return shape for {@link useDebouncedSearch}.
 */
export interface DebouncedSearch {
  /** The live input value (updates on every keystroke). */
  value: string;
  /** The debounced value (updates `delay` ms after the last keystroke). */
  debouncedValue: string;
  /** Update the live value. */
  setValue: (value: string) => void;
  /** Reset the live value to an empty string. */
  clear: () => void;
  /** True while the live value differs from the debounced value. */
  isDebouncing: boolean;
}

/**
 * Standardized debounced search input state.
 *
 * Owns the live input value and exposes a debounced copy suitable for query
 * keys / API params, so list pages don't re-implement `setTimeout` plumbing.
 *
 * @example
 * ```tsx
 * const search = useDebouncedSearch({ delay: 300 });
 * useQuery({ queryKey: keys.list(search.debouncedValue), queryFn: ... });
 * <Input value={search.value} onChange={(e) => search.setValue(e.target.value)} />
 * ```
 */
export function useDebouncedSearch(
  options: UseDebouncedSearchOptions = {},
): DebouncedSearch {
  const { delay = 300, initialValue = "", onDebouncedChange } = options;

  const [value, setValue] = useState(initialValue);
  const [debouncedValue, setDebouncedValue] = useState(initialValue);

  // Keep the latest callback in a ref so passing an inline function doesn't
  // re-arm the timer on every render.
  const callbackRef = useRef(onDebouncedChange);
  useEffect(() => {
    callbackRef.current = onDebouncedChange;
  }, [onDebouncedChange]);

  useEffect(() => {
    if (value === debouncedValue) return undefined;

    const timer = setTimeout(() => {
      setDebouncedValue(value);
      callbackRef.current?.(value);
    }, delay);

    return () => clearTimeout(timer);
  }, [value, debouncedValue, delay]);

  const clear = useCallback(() => setValue(""), []);

  return {
    value,
    debouncedValue,
    setValue,
    clear,
    isDebouncing: value !== debouncedValue,
  };
}
