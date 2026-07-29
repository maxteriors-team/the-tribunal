/**
 * Service-path selection in the Quote Builder.
 *
 * A quote covers exactly one service: landscape lighting, year-round permanent
 * LED track, and seasonal Christmas are three separate branches. These tests lock
 * down that a quote can never end up spanning two of them — neither by picking a
 * service nor by toggling an individual product line.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { salesWizardApi } from "@/lib/api/sales-wizard";
import type { Contact } from "@/types";

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

const SAVED_CLIENT = {
  id: 42,
  user_id: 1,
  first_name: "Max",
  last_name: "Sherrod",
  email: "max@maxteriors.com",
  phone_number: "2485550100",
  address_line1: "123 Oak Lane",
  address_city: "Birmingham",
  address_state: "MI",
  address_zip: "48009",
  status: "new",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
} as Contact;

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

describe("useSalesWizard client linking", () => {
  it("starts unlinked so a typed-in client is simply a new one", () => {
    const { result } = renderWizard();
    expect(result.current.linkedContactId).toBeNull();

    act(() => result.current.setClientField("first_name", "Maxwell"));
    expect(result.current.client.first_name).toBe("Maxwell");
    expect(result.current.linkedContactId).toBeNull();
  });

  it("picking a saved client fills the block and files the quote on it", async () => {
    const { result } = renderWizard();

    act(() => result.current.applyContact(SAVED_CLIENT));

    expect(result.current.linkedContactId).toBe(42);
    expect(result.current.client).toMatchObject({
      first_name: "Max",
      last_name: "Sherrod",
      email: "max@maxteriors.com",
      phone: "(248) 555-0100",
      street: "123 Oak Lane",
      city: "Birmingham",
      state: "MI",
      zip: "48009",
    });

    // The link rides along to the server, which would otherwise resolve (or
    // create) a contact from the loose email/phone.
    await waitFor(() =>
      expect(salesWizardApi.preview).toHaveBeenCalledWith(
        "ws-1",
        expect.objectContaining({ contact_id: 42 }),
      ),
    );
  });

  it("never wipes typed details with a blank field on the saved record", () => {
    const { result } = renderWizard();

    act(() => result.current.setClientField("street", "77 Elm Court"));
    act(() =>
      result.current.applyContact({
        ...SAVED_CLIENT,
        address_line1: undefined,
      } as Contact),
    );

    expect(result.current.client.street).toBe("77 Elm Court");
  });

  it("drops the link when the rep edits who the quote is for", () => {
    const { result } = renderWizard();

    act(() => result.current.applyContact(SAVED_CLIENT));
    act(() => result.current.setClientField("last_name", "Sherrodd"));
    expect(result.current.linkedContactId).toBeNull();

    // A different job site is still the same customer, so the link holds.
    act(() => result.current.applyContact(SAVED_CLIENT));
    act(() => result.current.setClientField("street", "900 Second Property"));
    act(() => result.current.setClientField("rep_name", "Maxwell"));
    expect(result.current.linkedContactId).toBe(42);
  });

  it("unlinks on request without clearing what was typed", () => {
    const { result } = renderWizard();

    act(() => result.current.applyContact(SAVED_CLIENT));
    act(() => result.current.clearLinkedContact());

    expect(result.current.linkedContactId).toBeNull();
    expect(result.current.client.first_name).toBe("Max");
    expect(result.current.client.email).toBe("max@maxteriors.com");
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
