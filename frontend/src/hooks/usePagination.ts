import { useCallback, useMemo, useState } from "react";

/**
 * Options for {@link usePagination}.
 */
export interface UsePaginationOptions {
  /** Initial 1-based page. Defaults to 1. */
  initialPage?: number;
  /** Initial page size. Defaults to 25. */
  initialPageSize?: number;
  /**
   * Total number of items across all pages. When provided, `totalPages`,
   * `canNextPage` and the displayed `range` are computed and `setPage` clamps
   * to the valid range. Leave undefined when the total is not yet known.
   */
  total?: number;
  /** Called whenever the active page changes (after clamping). */
  onPageChange?: (page: number) => void;
}

/**
 * Return shape for {@link usePagination}.
 */
export interface Pagination {
  /** Current 1-based page. */
  page: number;
  /** Current page size. */
  pageSize: number;
  /** Total pages when `total` is known, otherwise `undefined`. */
  totalPages: number | undefined;
  /** Set the page, clamped to `[1, totalPages]` when total is known. */
  setPage: (page: number) => void;
  /** Set the page size and reset back to page 1. */
  setPageSize: (size: number) => void;
  /** Go to the next page (no-op when already on the last page). */
  nextPage: () => void;
  /** Go to the previous page (no-op when already on the first page). */
  prevPage: () => void;
  /** True when there is a previous page. */
  canPrevPage: boolean;
  /** True when there is a next page (always true if total is unknown). */
  canNextPage: boolean;
  /** Reset back to the initial page. */
  reset: () => void;
  /**
   * 1-based inclusive item range shown on the current page, e.g. `{ from: 26,
   * to: 50 }`. `from` is 0 when there are no items.
   */
  range: { from: number; to: number };
}

/**
 * Standardized pagination state for list/table pages.
 *
 * Centralizes page/pageSize math (total pages, clamping, prev/next guards, the
 * displayed item range) so each page doesn't hand-roll it.
 *
 * @example
 * ```tsx
 * const pagination = usePagination({ initialPageSize: 50, total: data?.total });
 * useQuery({ queryKey: keys.list(pagination.page), ... });
 * <ResourceListPagination page={pagination.page} totalPages={pagination.totalPages} ... />
 * ```
 */
export function usePagination(options: UsePaginationOptions = {}): Pagination {
  const { initialPage = 1, initialPageSize = 25, total, onPageChange } = options;

  const [page, setPageState] = useState(initialPage);
  const [pageSize, setPageSizeState] = useState(initialPageSize);

  const totalPages = useMemo(() => {
    if (total === undefined) return undefined;
    return Math.max(1, Math.ceil(total / pageSize));
  }, [total, pageSize]);

  const setPage = useCallback(
    (next: number) => {
      setPageState((current) => {
        const lower = Math.max(1, next);
        const clamped = totalPages !== undefined ? Math.min(lower, totalPages) : lower;
        if (clamped !== current) onPageChange?.(clamped);
        return clamped;
      });
    },
    [totalPages, onPageChange],
  );

  const setPageSize = useCallback(
    (size: number) => {
      setPageSizeState(Math.max(1, size));
      setPageState((current) => {
        if (current !== 1) onPageChange?.(1);
        return 1;
      });
    },
    [onPageChange],
  );

  const nextPage = useCallback(() => setPage(page + 1), [page, setPage]);
  const prevPage = useCallback(() => setPage(page - 1), [page, setPage]);

  const reset = useCallback(() => {
    setPageState((current) => {
      if (current !== initialPage) onPageChange?.(initialPage);
      return initialPage;
    });
  }, [initialPage, onPageChange]);

  const canPrevPage = page > 1;
  const canNextPage = totalPages === undefined ? true : page < totalPages;

  const range = useMemo(() => {
    if (total !== undefined && total === 0) return { from: 0, to: 0 };
    const from = (page - 1) * pageSize + 1;
    const to = total !== undefined ? Math.min(page * pageSize, total) : page * pageSize;
    return { from, to };
  }, [page, pageSize, total]);

  return {
    page,
    pageSize,
    totalPages,
    setPage,
    setPageSize,
    nextPage,
    prevPage,
    canPrevPage,
    canNextPage,
    reset,
    range,
  };
}
