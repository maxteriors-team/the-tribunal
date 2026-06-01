import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { usePagination } from "./usePagination";

describe("usePagination", () => {
  it("uses the provided initial page and page size", () => {
    const { result } = renderHook(() =>
      usePagination({ initialPage: 2, initialPageSize: 10 }),
    );

    expect(result.current.page).toBe(2);
    expect(result.current.pageSize).toBe(10);
  });

  it("computes total pages from total and page size", () => {
    const { result } = renderHook(() => usePagination({ initialPageSize: 25, total: 101 }));

    expect(result.current.totalPages).toBe(5);
  });

  it("leaves total pages undefined when total is unknown", () => {
    const { result } = renderHook(() => usePagination({ initialPageSize: 25 }));

    expect(result.current.totalPages).toBeUndefined();
    expect(result.current.canNextPage).toBe(true);
  });

  it("clamps setPage to the valid range when total is known", () => {
    const { result } = renderHook(() => usePagination({ initialPageSize: 10, total: 25 }));

    act(() => result.current.setPage(99));
    expect(result.current.page).toBe(3);

    act(() => result.current.setPage(-5));
    expect(result.current.page).toBe(1);
  });

  it("guards next/prev at the boundaries", () => {
    const { result } = renderHook(() => usePagination({ initialPageSize: 10, total: 25 }));

    expect(result.current.canPrevPage).toBe(false);
    act(() => result.current.prevPage());
    expect(result.current.page).toBe(1);

    act(() => result.current.setPage(3));
    expect(result.current.canNextPage).toBe(false);
    act(() => result.current.nextPage());
    expect(result.current.page).toBe(3);
  });

  it("resets to page 1 when the page size changes", () => {
    const { result } = renderHook(() => usePagination({ initialPageSize: 10, total: 100 }));

    act(() => result.current.setPage(4));
    expect(result.current.page).toBe(4);

    act(() => result.current.setPageSize(50));
    expect(result.current.pageSize).toBe(50);
    expect(result.current.page).toBe(1);
  });

  it("computes the displayed item range", () => {
    const { result } = renderHook(() => usePagination({ initialPageSize: 25, total: 101 }));

    expect(result.current.range).toEqual({ from: 1, to: 25 });

    act(() => result.current.setPage(5));
    expect(result.current.range).toEqual({ from: 101, to: 101 });
  });

  it("returns a zeroed range when there are no items", () => {
    const { result } = renderHook(() => usePagination({ initialPageSize: 25, total: 0 }));

    expect(result.current.range).toEqual({ from: 0, to: 0 });
    expect(result.current.totalPages).toBe(1);
  });

  it("fires onPageChange only when the page actually changes", () => {
    const onPageChange = vi.fn();
    const { result } = renderHook(() =>
      usePagination({ initialPageSize: 10, total: 100, onPageChange }),
    );

    act(() => result.current.setPage(2));
    expect(onPageChange).toHaveBeenCalledTimes(1);
    expect(onPageChange).toHaveBeenCalledWith(2);

    act(() => result.current.setPage(2));
    expect(onPageChange).toHaveBeenCalledTimes(1);
  });
});
