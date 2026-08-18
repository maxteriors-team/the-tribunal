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
  hydrationForQuote,
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
    getQuote: vi.fn(),
    save: vi.fn(),
    update: vi.fn(),
    revise: vi.fn(),
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

function renderWizard(service?: ServiceKey, quoteId: string | null = null) {
  return renderHook(() => useSalesWizard("ws-1", service, quoteId), { wrapper });
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

describe("useSalesWizard quote hydration and revision saves", () => {
  const proposalInput = {
    pricing_source: "workspace_rules" as const,
    contact_id: 42,
    service_location_id: "location-1",
    opportunity_id: "opportunity-1",
    lighting_project_id: "project-1",
    title: "Saved design",
    notes: "Keep the oak lit",
    terms: "Thirty days",
    client: {
      first_name: "Sarah",
      last_name: "Henderson",
      email: "sarah@example.com",
      phone: "+12485550100",
      rep_name: "Max",
      street: "123 Oak",
      city: "Birmingham",
      state: "MI",
      zip: "48009",
    },
    quantities: [{ item_id: "fixture-1", quantity: 12 }],
    additional_charges: [
      {
        description: "Core drilling",
        net_amount: 500,
        catalog_item_id: null,
        tier_key: "best",
      },
    ],
    selected_tier: "best",
    care_plan_tier: "premier",
    care_count_manual: 14,
    categories: ["landscape", "bistro"],
    bistro: { product: "color" as const, tier: "medium", feet: 120 },
    permanent: null,
    christmas: null,
    night_preview: {
      images: ["https://cdn.example/night.jpg"],
      services: ["landscape"],
    },
    mockups: [{ image: "https://cdn.example/mock.jpg", caption: "Front walk" }],
    deposit: { mode: "fixed" as const, value: 875 },
  };

  function editableQuote(
    overrides: Record<string, unknown> = {},
  ): Awaited<ReturnType<typeof salesWizardApi.getQuote>> {
    return {
      id: "source-quote",
      workspace_id: "ws-1",
      number: "QUO-001",
      title: "Saved design",
      status: "approved",
      subtotal: 1000,
      tax_amount: 0,
      discount_amount: 0,
      total: 1000,
      currency: "USD",
      line_items: [],
      proposal_document: null,
      proposal_input: proposalInput,
      proposal_input_version: 1,
      is_wizard_quote: true,
      wizard_edit_mode: "revise",
      revision_number: 1,
      proposal_version: 1,
      created_at: "2026-08-18T00:00:00Z",
      updated_at: "2026-08-18T00:00:00Z",
      ...overrides,
    } as unknown as Awaited<ReturnType<typeof salesWizardApi.getQuote>>;
  }

  it("hydrates every saved selection and preserves linked metadata on revision", async () => {
    vi.mocked(salesWizardApi.getQuote).mockResolvedValue(editableQuote());
    vi.mocked(salesWizardApi.revise).mockResolvedValue(
      editableQuote({
        id: "revision-quote",
        number: "QUO-002",
        status: "draft",
        wizard_edit_mode: "update",
        revision_number: 2,
      }),
    );
    vi.mocked(salesWizardApi.update).mockResolvedValue(
      editableQuote({
        id: "revision-quote",
        number: "QUO-002",
        status: "draft",
        wizard_edit_mode: "update",
        revision_number: 2,
      }),
    );

    const { result } = renderWizard(undefined, "source-quote");
    await waitFor(() => expect(result.current.hydrationSource).toBe("input"));

    expect(result.current.client).toMatchObject({
      first_name: "Sarah",
      email: "sarah@example.com",
      street: "123 Oak",
    });
    expect(result.current.linkedContactId).toBe(42);
    expect(result.current.quantities).toEqual({ "fixture-1": 12 });
    expect(result.current.charges[0]).toMatchObject({
      description: "Core drilling",
      amount: "500",
      tierKey: "best",
    });
    expect(result.current.categories).toEqual(["landscape", "bistro"]);
    expect(result.current.bistro).toEqual({
      product: "color",
      tier: "medium",
      feet: "120",
    });
    expect(result.current.depositMode).toBe("fixed");
    expect(result.current.depositInput).toBe("875");
    expect(result.current.mockups).toEqual([
      { image: "https://cdn.example/mock.jpg", caption: "Front walk" },
    ]);

    act(() => result.current.setQty("fixture-1", 18));
    await act(async () => {
      await result.current.save();
    });
    expect(salesWizardApi.revise).toHaveBeenCalledWith(
      "ws-1",
      "source-quote",
      expect.objectContaining({
        contact_id: 42,
        service_location_id: "location-1",
        opportunity_id: "opportunity-1",
        lighting_project_id: "project-1",
        title: "Saved design",
        notes: "Keep the oak lit",
        terms: "Thirty days",
        quantities: [{ item_id: "fixture-1", quantity: 18 }],
      }),
    );

    await act(async () => {
      await result.current.save();
    });
    expect(salesWizardApi.update).toHaveBeenCalledWith(
      "ws-1",
      "revision-quote",
      expect.any(Object),
    );
  });

  it("surfaces quote loading failures and retries into hydrated state", async () => {
    vi.mocked(salesWizardApi.getQuote)
      .mockRejectedValueOnce(new Error("not found"))
      .mockResolvedValueOnce(
        editableQuote({ status: "sent", wizard_edit_mode: "update" }),
      );

    const { result } = renderWizard(undefined, "source-quote");
    expect(result.current.isLoadingQuote).toBe(true);
    await waitFor(() => expect(result.current.quoteLoadError).toBe(true));

    act(() => result.current.reloadQuote());
    await waitFor(() => expect(result.current.quoteLoadError).toBe(false));
    await waitFor(() => expect(result.current.hydrationSource).toBe("input"));
    expect(result.current.editMode).toBe("update");
  });

  it("recovers legacy snapshot quantities and flags the hydration as lossy", () => {
    const hydration = hydrationForQuote(
      editableQuote({
        proposal_input: null,
        proposal_document: {
          pricing_source: "price_book",
          categories: ["landscape"],
          selected_tier: "best",
          client: { first_name: "Legacy" },
          tiers: [
            {
              key: "best",
              lines: [{ item_id: "fixture-old", quantity: 7 }],
            },
          ],
          additional_charges: [
            { description: "Trenching", amount: 200, tier_key: "best" },
          ],
        },
      }),
    );

    expect(hydration.source).toBe("snapshot");
    expect(hydration.payload.quantities).toEqual([
      { item_id: "fixture-old", quantity: 7 },
    ]);
    expect((hydration.payload.additional_charges ?? [])[0]).toMatchObject({
      description: "Trenching",
      net_amount: 200,
    });
  });
});