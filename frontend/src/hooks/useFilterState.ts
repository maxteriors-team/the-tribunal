import { useCallback, useMemo, useState } from "react";

/** A record of filter values keyed by filter name. */
export type FilterValues = Record<string, unknown>;

/**
 * Options for {@link useFilterState}.
 */
export interface UseFilterStateOptions<TFilters extends FilterValues> {
  /** Initial filter values. Also used as the baseline for `activeCount`/`reset`. */
  initialFilters: TFilters;
  /**
   * Called whenever any filter changes. List pages typically pass
   * `pagination.reset` here so changing a filter returns to page 1.
   */
  onChange?: (filters: TFilters) => void;
}

/**
 * Return shape for {@link useFilterState}.
 */
export interface FilterState<TFilters extends FilterValues> {
  /** Current filter values. */
  filters: TFilters;
  /** Update a single filter by key. */
  setFilter: <K extends keyof TFilters>(key: K, value: TFilters[K]) => void;
  /** Merge a partial set of filter values. */
  setFilters: (partial: Partial<TFilters>) => void;
  /** Reset all filters back to their initial values. */
  reset: () => void;
  /**
   * Number of filters that differ from their initial value. `0` means the list
   * is in its default, unfiltered state.
   */
  activeCount: number;
  /** True when `activeCount > 0`. */
  hasActiveFilters: boolean;
}

function shallowEqual(a: unknown, b: unknown): boolean {
  return Object.is(a, b);
}

/**
 * Standardized filter state for list/table pages.
 *
 * Holds an arbitrary, typed bag of filters, tracks how many differ from the
 * defaults, and fires `onChange` so callers can reset pagination. Search text
 * lives in {@link useDebouncedSearch}; this is for selects/toggles/etc.
 *
 * @example
 * ```tsx
 * const filterState = useFilterState({
 *   initialFilters: { status: "all", direction: "all" },
 *   onChange: () => pagination.reset(),
 * });
 * <Select value={filterState.filters.status} onValueChange={(v) => filterState.setFilter("status", v)} />
 * ```
 */
export function useFilterState<TFilters extends FilterValues>(
  options: UseFilterStateOptions<TFilters>,
): FilterState<TFilters> {
  const { initialFilters, onChange } = options;

  // Snapshot the initial filters once so `reset`/`activeCount` have a stable
  // baseline even if the caller passes a new object literal each render.
  const [baseline] = useState(initialFilters);
  const [filters, setFiltersState] = useState<TFilters>(initialFilters);

  const applyChange = useCallback(
    (next: TFilters) => {
      setFiltersState(next);
      onChange?.(next);
    },
    [onChange],
  );

  const setFilter = useCallback(
    <K extends keyof TFilters>(key: K, value: TFilters[K]) => {
      setFiltersState((current) => {
        if (shallowEqual(current[key], value)) return current;
        const next = { ...current, [key]: value };
        onChange?.(next);
        return next;
      });
    },
    [onChange],
  );

  const setFilters = useCallback(
    (partial: Partial<TFilters>) => {
      setFiltersState((current) => {
        const next = { ...current, ...partial };
        onChange?.(next);
        return next;
      });
    },
    [onChange],
  );

  const reset = useCallback(() => {
    applyChange(baseline);
  }, [applyChange, baseline]);

  const activeCount = useMemo(() => {
    return Object.keys(filters).reduce((count, key) => {
      return shallowEqual(filters[key], baseline[key]) ? count : count + 1;
    }, 0);
  }, [filters, baseline]);

  return {
    filters,
    setFilter,
    setFilters,
    reset,
    activeCount,
    hasActiveFilters: activeCount > 0,
  };
}
