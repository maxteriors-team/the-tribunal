import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useResourceList } from "./useResourceList";

type Filters = {
  status: string;
};

describe("useResourceList", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
  });

  it("composes search, pagination, filters and selection", () => {
    const { result } = renderHook(() =>
      useResourceList<Filters, number>({
        search: { delay: 200 },
        pagination: { initialPageSize: 25, total: 100 },
        initialFilters: { status: "all" },
        rowIds: [1, 2, 3],
      }),
    );

    expect(result.current.search.debouncedValue).toBe("");
    expect(result.current.pagination.page).toBe(1);
    expect(result.current.filters.activeCount).toBe(0);
    expect(result.current.selection.selectedCount).toBe(0);
  });

  it("resets pagination to page 1 when the debounced search changes", () => {
    const { result } = renderHook(() =>
      useResourceList<Filters, number>({
        search: { delay: 200 },
        pagination: { initialPageSize: 10, total: 100 },
        initialFilters: { status: "all" },
        rowIds: [1, 2, 3],
      }),
    );

    act(() => result.current.pagination.setPage(4));
    expect(result.current.pagination.page).toBe(4);

    act(() => result.current.search.setValue("acme"));
    act(() => {
      vi.advanceTimersByTime(200);
    });

    expect(result.current.search.debouncedValue).toBe("acme");
    expect(result.current.pagination.page).toBe(1);
  });

  it("resets pagination to page 1 when a filter changes", () => {
    const { result } = renderHook(() =>
      useResourceList<Filters, number>({
        pagination: { initialPageSize: 10, total: 100 },
        initialFilters: { status: "all" },
        rowIds: [1, 2, 3],
      }),
    );

    act(() => result.current.pagination.setPage(3));
    expect(result.current.pagination.page).toBe(3);

    act(() => result.current.filters.setFilter("status", "won"));
    expect(result.current.pagination.page).toBe(1);
    expect(result.current.filters.activeCount).toBe(1);
  });
});
