import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useFilterState } from "./useFilterState";

type Filters = {
  status: string;
  direction: string;
};

const INITIAL: Filters = { status: "all", direction: "all" };

describe("useFilterState", () => {
  it("starts with the initial filters and no active count", () => {
    const { result } = renderHook(() => useFilterState({ initialFilters: INITIAL }));

    expect(result.current.filters).toEqual(INITIAL);
    expect(result.current.activeCount).toBe(0);
    expect(result.current.hasActiveFilters).toBe(false);
  });

  it("sets a single filter and tracks the active count", () => {
    const { result } = renderHook(() => useFilterState({ initialFilters: INITIAL }));

    act(() => result.current.setFilter("status", "completed"));

    expect(result.current.filters.status).toBe("completed");
    expect(result.current.activeCount).toBe(1);
    expect(result.current.hasActiveFilters).toBe(true);
  });

  it("merges partial filters", () => {
    const { result } = renderHook(() => useFilterState({ initialFilters: INITIAL }));

    act(() => result.current.setFilters({ status: "completed", direction: "inbound" }));

    expect(result.current.filters).toEqual({ status: "completed", direction: "inbound" });
    expect(result.current.activeCount).toBe(2);
  });

  it("does not count a filter set back to its default value", () => {
    const { result } = renderHook(() => useFilterState({ initialFilters: INITIAL }));

    act(() => result.current.setFilter("status", "completed"));
    expect(result.current.activeCount).toBe(1);

    act(() => result.current.setFilter("status", "all"));
    expect(result.current.activeCount).toBe(0);
  });

  it("resets every filter to its initial value", () => {
    const { result } = renderHook(() => useFilterState({ initialFilters: INITIAL }));

    act(() => result.current.setFilters({ status: "completed", direction: "inbound" }));
    act(() => result.current.reset());

    expect(result.current.filters).toEqual(INITIAL);
    expect(result.current.activeCount).toBe(0);
  });

  it("fires onChange when a filter changes but not when the value is unchanged", () => {
    const onChange = vi.fn();
    const { result } = renderHook(() =>
      useFilterState({ initialFilters: INITIAL, onChange }),
    );

    act(() => result.current.setFilter("status", "completed"));
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith({ status: "completed", direction: "all" });

    act(() => result.current.setFilter("status", "completed"));
    expect(onChange).toHaveBeenCalledTimes(1);
  });
});
