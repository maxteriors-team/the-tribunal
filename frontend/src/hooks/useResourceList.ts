import { useMemo } from "react";

import {
  useDebouncedSearch,
  type DebouncedSearch,
  type UseDebouncedSearchOptions,
} from "@/hooks/useDebouncedSearch";
import {
  useFilterState,
  type FilterState,
  type FilterValues,
} from "@/hooks/useFilterState";
import {
  usePagination,
  type Pagination,
  type UsePaginationOptions,
} from "@/hooks/usePagination";
import {
  useRowSelection,
  type RowId,
  type RowSelection,
} from "@/hooks/useRowSelection";

/**
 * Options for {@link useResourceList}.
 */
export interface UseResourceListOptions<TFilters extends FilterValues, TId extends RowId> {
  /** Debounced search configuration (delay, initial value). */
  search?: Omit<UseDebouncedSearchOptions, "onDebouncedChange">;
  /** Pagination configuration. Pass `total` once the data is loaded. */
  pagination?: Omit<UsePaginationOptions, "onPageChange">;
  /** Initial filter values for the typed filter bag. */
  initialFilters: TFilters;
  /** Visible row IDs (current page) for selection/range/select-all helpers. */
  rowIds: readonly TId[];
}

/**
 * Return shape for {@link useResourceList}.
 */
export interface ResourceList<TFilters extends FilterValues, TId extends RowId> {
  search: DebouncedSearch;
  pagination: Pagination;
  filters: FilterState<TFilters>;
  selection: RowSelection<TId>;
}

/**
 * One-stop composition of the standardized list primitives.
 *
 * Wires debounced search, pagination, filter state, and row selection together
 * so that changing the search term or any filter automatically resets back to
 * page 1. Use this for list/table pages that need all four; reach for the
 * individual hooks when you only need a subset.
 *
 * @example
 * ```tsx
 * const list = useResourceList({
 *   search: { delay: 300 },
 *   pagination: { initialPageSize: 50, total: data?.total },
 *   initialFilters: { status: "all", direction: "all" },
 *   rowIds: rows.map((r) => r.id),
 * });
 * useQuery({
 *   queryKey: keys.list(list.search.debouncedValue, list.filters.filters, list.pagination.page),
 *   ...
 * });
 * ```
 */
export function useResourceList<TFilters extends FilterValues, TId extends RowId = RowId>(
  options: UseResourceListOptions<TFilters, TId>,
): ResourceList<TFilters, TId> {
  const { search: searchOptions, pagination: paginationOptions, initialFilters, rowIds } = options;

  const pagination = usePagination(paginationOptions);
  const { reset: resetPage } = pagination;

  const search = useDebouncedSearch({
    ...searchOptions,
    onDebouncedChange: resetPage,
  });

  const filters = useFilterState<TFilters>({
    initialFilters,
    onChange: resetPage,
  });

  const stableRowIds = useMemo(() => rowIds, [rowIds]);
  const selection = useRowSelection<TId>({ rowIds: stableRowIds });

  return { search, pagination, filters, selection };
}
