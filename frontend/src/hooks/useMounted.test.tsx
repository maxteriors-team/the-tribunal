import { renderHook } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { useIsMounted } from "./useMounted";

function Probe() {
  return <>{String(useIsMounted())}</>;
}

describe("useIsMounted", () => {
  // Regression: branching on browser-only state (next-themes `resolvedTheme`)
  // during SSR made the server emit a different theme icon than the client,
  // which forced React to throw away the hydrated app-shell tree.
  it("returns false while server rendering so SSR markup stays browser-state free", () => {
    expect(renderToString(<Probe />)).toBe("false");
  });

  it("returns true on the client", () => {
    const { result } = renderHook(() => useIsMounted());

    expect(result.current).toBe(true);
  });
});
