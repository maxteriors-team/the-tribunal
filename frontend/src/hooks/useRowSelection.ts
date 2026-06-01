import { useCallback, useMemo, useState } from "react";

/** ID types supported by row selection. */
export type RowId = string | number;

/**
 * Options for {@link useRowSelection}.
 */
export interface UseRowSelectionOptions<TId extends RowId> {
  /**
   * The IDs currently visible/selectable (e.g. the current page). Used to
   * compute "select all visible" state and to resolve shift-click ranges. The
   * order must match the on-screen order for range selection to work.
   */
  rowIds: readonly TId[];
}

/**
 * Return shape for {@link useRowSelection}.
 */
export interface RowSelection<TId extends RowId> {
  /** The set of selected IDs (stable reference between renders when unchanged). */
  selectedIds: ReadonlySet<TId>;
  /** Selected IDs as an array, in insertion order. */
  selectedArray: TId[];
  /** Number of selected rows. */
  selectedCount: number;
  /** True when at least one row is selected. */
  hasSelection: boolean;
  /** True when a given row id is selected. */
  isSelected: (id: TId) => boolean;
  /**
   * Toggle a single row. Pass `shiftKey` to range-select from the last
   * interacted row to this one (inclusive) using `rowIds` order.
   */
  toggle: (id: TId, shiftKey?: boolean) => void;
  /** Explicitly set a single row's selection state. */
  setSelected: (id: TId, selected: boolean) => void;
  /** True when every visible row (`rowIds`) is selected. */
  allVisibleSelected: boolean;
  /** True when some — but not all — visible rows are selected. */
  someVisibleSelected: boolean;
  /**
   * Toggle all visible rows: selects every visible row unless they are all
   * already selected, in which case it deselects them.
   */
  toggleAllVisible: () => void;
  /** Replace the entire selection with the given ids. */
  selectIds: (ids: Iterable<TId>) => void;
  /** Clear the selection. */
  clear: () => void;
}

/**
 * Standardized multi-row selection for tables/lists with bulk actions.
 *
 * Handles the fiddly bits every selectable list needs: a stable selected set,
 * shift-click range selection, header "select all visible" tri-state, and bulk
 * helpers — so feature pages don't re-implement them.
 *
 * @example
 * ```tsx
 * const selection = useRowSelection({ rowIds: rows.map((r) => r.id) });
 * <Checkbox
 *   checked={selection.allVisibleSelected ? true : selection.someVisibleSelected ? "indeterminate" : false}
 *   onCheckedChange={selection.toggleAllVisible}
 * />
 * ```
 */
export function useRowSelection<TId extends RowId>(
  options: UseRowSelectionOptions<TId>,
): RowSelection<TId> {
  const { rowIds } = options;

  const [selectedIds, setSelectedIds] = useState<Set<TId>>(() => new Set());
  const [lastIndex, setLastIndex] = useState<number | null>(null);

  const isSelected = useCallback((id: TId) => selectedIds.has(id), [selectedIds]);

  const setSelected = useCallback((id: TId, selected: boolean) => {
    setSelectedIds((prev) => {
      if (selected === prev.has(id)) return prev;
      const next = new Set(prev);
      if (selected) next.add(id);
      else next.delete(id);
      return next;
    });
  }, []);

  const toggle = useCallback(
    (id: TId, shiftKey = false) => {
      const currentIndex = rowIds.indexOf(id);

      if (shiftKey && lastIndex !== null && currentIndex !== -1) {
        const start = Math.min(lastIndex, currentIndex);
        const end = Math.max(lastIndex, currentIndex);
        setSelectedIds((prev) => {
          const next = new Set(prev);
          for (let i = start; i <= end; i++) next.add(rowIds[i]);
          return next;
        });
        setLastIndex(currentIndex);
        return;
      }

      setSelectedIds((prev) => {
        const next = new Set(prev);
        if (next.has(id)) next.delete(id);
        else next.add(id);
        return next;
      });
      if (currentIndex !== -1) setLastIndex(currentIndex);
    },
    [rowIds, lastIndex],
  );

  const allVisibleSelected = rowIds.length > 0 && rowIds.every((id) => selectedIds.has(id));
  const someVisibleSelected = rowIds.some((id) => selectedIds.has(id));

  const toggleAllVisible = useCallback(() => {
    setSelectedIds((prev) => {
      const everySelected = rowIds.length > 0 && rowIds.every((id) => prev.has(id));
      const next = new Set(prev);
      if (everySelected) {
        rowIds.forEach((id) => next.delete(id));
      } else {
        rowIds.forEach((id) => next.add(id));
      }
      return next;
    });
  }, [rowIds]);

  const selectIds = useCallback((ids: Iterable<TId>) => {
    setSelectedIds(new Set(ids));
    setLastIndex(null);
  }, []);

  const clear = useCallback(() => {
    setSelectedIds((prev) => (prev.size === 0 ? prev : new Set()));
    setLastIndex(null);
  }, []);

  const selectedArray = useMemo(() => Array.from(selectedIds), [selectedIds]);

  return {
    selectedIds,
    selectedArray,
    selectedCount: selectedIds.size,
    hasSelection: selectedIds.size > 0,
    isSelected,
    toggle,
    setSelected,
    allVisibleSelected,
    someVisibleSelected,
    toggleAllVisible,
    selectIds,
    clear,
  };
}
