import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useRowSelection } from "./useRowSelection";

const ROWS = [1, 2, 3, 4, 5];

describe("useRowSelection", () => {
  it("starts empty", () => {
    const { result } = renderHook(() => useRowSelection({ rowIds: ROWS }));

    expect(result.current.selectedCount).toBe(0);
    expect(result.current.hasSelection).toBe(false);
    expect(result.current.allVisibleSelected).toBe(false);
    expect(result.current.someVisibleSelected).toBe(false);
  });

  it("toggles a single row on and off", () => {
    const { result } = renderHook(() => useRowSelection({ rowIds: ROWS }));

    act(() => result.current.toggle(2));
    expect(result.current.isSelected(2)).toBe(true);
    expect(result.current.selectedCount).toBe(1);

    act(() => result.current.toggle(2));
    expect(result.current.isSelected(2)).toBe(false);
    expect(result.current.selectedCount).toBe(0);
  });

  it("range-selects with shift-click using row order", () => {
    const { result } = renderHook(() => useRowSelection({ rowIds: ROWS }));

    act(() => result.current.toggle(2));
    act(() => result.current.toggle(4, true));

    expect(result.current.selectedArray.sort()).toEqual([2, 3, 4]);
  });

  it("computes tri-state header selection", () => {
    const { result } = renderHook(() => useRowSelection({ rowIds: ROWS }));

    act(() => result.current.toggle(1));
    expect(result.current.someVisibleSelected).toBe(true);
    expect(result.current.allVisibleSelected).toBe(false);

    act(() => result.current.toggleAllVisible());
    expect(result.current.allVisibleSelected).toBe(true);
    expect(result.current.selectedCount).toBe(ROWS.length);
  });

  it("toggleAllVisible clears when everything is already selected", () => {
    const { result } = renderHook(() => useRowSelection({ rowIds: ROWS }));

    act(() => result.current.toggleAllVisible());
    expect(result.current.allVisibleSelected).toBe(true);

    act(() => result.current.toggleAllVisible());
    expect(result.current.selectedCount).toBe(0);
  });

  it("setSelected explicitly sets state without toggling", () => {
    const { result } = renderHook(() => useRowSelection({ rowIds: ROWS }));

    act(() => result.current.setSelected(3, true));
    act(() => result.current.setSelected(3, true));
    expect(result.current.selectedCount).toBe(1);

    act(() => result.current.setSelected(3, false));
    expect(result.current.selectedCount).toBe(0);
  });

  it("selectIds replaces the whole selection and clear empties it", () => {
    const { result } = renderHook(() => useRowSelection({ rowIds: ROWS }));

    act(() => result.current.selectIds([1, 5]));
    expect(result.current.selectedArray.sort()).toEqual([1, 5]);

    act(() => result.current.clear());
    expect(result.current.selectedCount).toBe(0);
  });

  it("supports string ids", () => {
    const { result } = renderHook(() => useRowSelection({ rowIds: ["a", "b", "c"] }));

    act(() => result.current.toggle("a"));
    act(() => result.current.toggle("c", true));
    expect(result.current.selectedArray.sort()).toEqual(["a", "b", "c"]);
  });
});
