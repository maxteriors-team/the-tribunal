import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useDebouncedSearch } from "./useDebouncedSearch";

describe("useDebouncedSearch", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
  });

  it("updates the live value immediately but debounces the debounced value", () => {
    const { result } = renderHook(() => useDebouncedSearch({ delay: 300 }));

    act(() => result.current.setValue("ab"));

    expect(result.current.value).toBe("ab");
    expect(result.current.debouncedValue).toBe("");
    expect(result.current.isDebouncing).toBe(true);

    act(() => {
      vi.advanceTimersByTime(300);
    });

    expect(result.current.debouncedValue).toBe("ab");
    expect(result.current.isDebouncing).toBe(false);
  });

  it("resets the timer on rapid successive changes (only the last value lands)", () => {
    const { result } = renderHook(() => useDebouncedSearch({ delay: 300 }));

    act(() => result.current.setValue("a"));
    act(() => {
      vi.advanceTimersByTime(200);
    });
    act(() => result.current.setValue("ab"));
    act(() => {
      vi.advanceTimersByTime(200);
    });

    // 400ms total elapsed, but only 200ms since the last change.
    expect(result.current.debouncedValue).toBe("");

    act(() => {
      vi.advanceTimersByTime(100);
    });

    expect(result.current.debouncedValue).toBe("ab");
  });

  it("calls onDebouncedChange with the settled value", () => {
    const onDebouncedChange = vi.fn();
    const { result } = renderHook(() =>
      useDebouncedSearch({ delay: 200, onDebouncedChange }),
    );

    act(() => result.current.setValue("hello"));
    act(() => {
      vi.advanceTimersByTime(200);
    });

    expect(onDebouncedChange).toHaveBeenCalledTimes(1);
    expect(onDebouncedChange).toHaveBeenCalledWith("hello");
  });

  it("clears the value back to empty", () => {
    const { result } = renderHook(() => useDebouncedSearch({ delay: 100, initialValue: "seed" }));

    expect(result.current.value).toBe("seed");

    act(() => result.current.clear());
    expect(result.current.value).toBe("");

    act(() => {
      vi.advanceTimersByTime(100);
    });
    expect(result.current.debouncedValue).toBe("");
  });

  it("honors the initial value without an initial debounce", () => {
    const onDebouncedChange = vi.fn();
    const { result } = renderHook(() =>
      useDebouncedSearch({ delay: 300, initialValue: "preset", onDebouncedChange }),
    );

    expect(result.current.value).toBe("preset");
    expect(result.current.debouncedValue).toBe("preset");
    expect(result.current.isDebouncing).toBe(false);

    act(() => {
      vi.advanceTimersByTime(300);
    });
    expect(onDebouncedChange).not.toHaveBeenCalled();
  });
});
