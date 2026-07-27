/**
 * Service-path selection in the Quote Builder.
 *
 * A quote covers exactly one service: landscape lighting, year-round permanent
 * LED track, and seasonal Christmas are three separate branches. These tests lock
 * down that a quote can never end up spanning two of them — neither by picking a
 * service nor by toggling an individual product line.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import {
  SERVICE_CATEGORIES,
  serviceForCategories,
  serviceForCategory,
  useSalesWizard,
  type ServiceKey,
} from "./use-sales-wizard";

// The hook fetches pricing + catalog on mount; neither drives selection, so both
// resolve empty. Selection is pure client state.
vi.mock("@/lib/api/sales-wizard", () => ({
  salesWizardApi: {
    getPricing: vi.fn().mockResolvedValue({}),
    listCatalog: vi.fn().mockResolvedValue([]),
    preview: vi.fn().mockResolvedValue({}),
    save: vi.fn(),
    send: vi.fn(),
    deliver: vi.fn(),
  },
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function renderWizard(service?: ServiceKey) {
  return renderHook(() => useSalesWizard("ws-1", service), { wrapper });
}

describe("service paths", () => {
  it("maps every product line to exactly one service", () => {
    expect(serviceForCategory("landscape")).toBe("landscape");
    expect(serviceForCategory("bistro")).toBe("landscape");
    expect(serviceForCategory("permanent")).toBe("permanent");
    expect(serviceForCategory("christmas")).toBe("christmas");
    // Christmas is its own path — not fused to permanent.
    expect(SERVICE_CATEGORIES.christmas).not.toContain("permanent");
    expect(SERVICE_CATEGORIES.permanent).not.toContain("christmas");
  });

  it("resolves a selection to its service and defaults to landscape", () => {
    expect(serviceForCategories(["christmas"])).toBe("christmas");
    expect(serviceForCategories(["permanent"])).toBe("permanent");
    expect(serviceForCategories(["landscape", "bistro"])).toBe("landscape");
    expect(serviceForCategories([])).toBe("landscape");
  });
});

describe("useSalesWizard service selection", () => {
  it("starts on landscape, or on the deep-linked service", () => {
    expect(renderWizard().result.current.activeService).toBe("landscape");
    expect(renderWizard("christmas").result.current.categories).toEqual([
      "christmas",
    ]);
    expect(renderWizard("permanent").result.current.activeService).toBe(
      "permanent",
    );
  });

  it("picking the christmas service clears landscape AND permanent lines", () => {
    const { result } = renderWizard();

    // Build up a landscape quote (landscape + its opt-in bistro line) first.
    act(() => result.current.toggleCategory("bistro"));
    expect(result.current.categories).toEqual(["landscape", "bistro"]);

    act(() => result.current.setService("christmas"));
    expect(result.current.categories).toEqual(["christmas"]);
    expect(result.current.activeService).toBe("christmas");
    expect(result.current.hasCategory("landscape")).toBe(false);
    expect(result.current.hasCategory("bistro")).toBe(false);
    expect(result.current.hasCategory("permanent")).toBe(false);
  });

  it("picking the permanent service clears christmas (the 3-way split)", () => {
    const { result } = renderWizard("christmas");

    act(() => result.current.setService("permanent"));
    expect(result.current.categories).toEqual(["permanent"]);
    expect(result.current.hasCategory("christmas")).toBe(false);

    // …and back the other way, so neither side is the privileged one.
    act(() => result.current.setService("christmas"));
    expect(result.current.categories).toEqual(["christmas"]);
    expect(result.current.hasCategory("permanent")).toBe(false);
  });

  it("toggling a line from another service switches branch instead of mixing", () => {
    const { result } = renderWizard();

    act(() => result.current.toggleCategory("christmas"));
    expect(result.current.categories).toEqual(["christmas"]);
    expect(result.current.activeService).toBe("christmas");

    act(() => result.current.toggleCategory("permanent"));
    expect(result.current.categories).toEqual(["permanent"]);
    expect(result.current.activeService).toBe("permanent");
  });

  it("keeps line toggling permissive within the active service", () => {
    const { result } = renderWizard();

    // Bistro belongs to landscape, so it adds to the quote rather than switching.
    act(() => result.current.toggleCategory("bistro"));
    expect(result.current.categories).toEqual(["landscape", "bistro"]);
    expect(result.current.activeService).toBe("landscape");

    act(() => result.current.toggleCategory("bistro"));
    expect(result.current.categories).toEqual(["landscape"]);
  });
});
