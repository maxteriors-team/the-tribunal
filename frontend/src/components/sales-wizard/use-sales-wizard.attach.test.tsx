/**
 * The attach prompt's lifecycle inside the Quote Builder.
 *
 * The prompt is server-derived (the live preview says whether this selection is
 * missing its add-on) but the *skip* is client state that has to be carried onto
 * the save. These tests lock down the two ways that pairing can go wrong: a skip
 * that outlives the prompt it answered, and a skip that reaches the server as
 * anything other than a bare reason.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { salesWizardApi } from "@/lib/api/sales-wizard";
import type { AttachWarning } from "@/types/sales-wizard";

import { useSalesWizard } from "./use-sales-wizard";

vi.mock("@/lib/api/sales-wizard", () => ({
  salesWizardApi: {
    getPricing: vi.fn().mockResolvedValue({}),
    listCatalog: vi.fn().mockResolvedValue([]),
    preview: vi.fn(),
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

function warning(overrides: Partial<AttachWarning> = {}): AttachWarning {
  return {
    primary_service: "roof",
    suggested_categories: ["gutters"],
    mode: "advisory",
    message: "This is a roof job with no add-on attached.",
    dismissal_reasons: ["Customer declined"],
    require_dismissal_reason: true,
    ...overrides,
  };
}

/** Make the debounced preview resolve with a given warning (or none). */
function previewReturns(attach: AttachWarning | null) {
  vi.mocked(salesWizardApi.preview).mockResolvedValue({
    attach_warning: attach,
  } as Awaited<ReturnType<typeof salesWizardApi.preview>>);
}

describe("useSalesWizard attach prompt", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(salesWizardApi.getPricing).mockResolvedValue(
      {} as Awaited<ReturnType<typeof salesWizardApi.getPricing>>,
    );
    vi.mocked(salesWizardApi.listCatalog).mockResolvedValue([]);
    previewReturns(warning());
  });

  it("surfaces the prompt the live preview reports", async () => {
    const { result } = renderHook(() => useSalesWizard("ws-1"), { wrapper });

    await waitFor(() =>
      expect(result.current.attachWarning?.primary_service).toBe("roof"),
    );
  });

  it("hides the prompt once it is skipped", async () => {
    const { result } = renderHook(() => useSalesWizard("ws-1"), { wrapper });
    await waitFor(() => expect(result.current.attachWarning).not.toBeNull());

    act(() => result.current.dismissAttach("Customer declined"));

    expect(result.current.attachWarning).toBeNull();
  });

  it("sends only the reason to the server, never a client-chosen category", async () => {
    vi.mocked(salesWizardApi.save).mockResolvedValue({
      id: "q1",
    } as Awaited<ReturnType<typeof salesWizardApi.save>>);
    vi.mocked(salesWizardApi.send).mockResolvedValue({
      id: "q1",
    } as Awaited<ReturnType<typeof salesWizardApi.send>>);

    const { result } = renderHook(() => useSalesWizard("ws-1"), { wrapper });
    await waitFor(() => expect(result.current.attachWarning).not.toBeNull());

    act(() => result.current.dismissAttach("Customer declined"));
    await act(async () => {
      await result.current.save();
    });

    const [, payload] = vi.mocked(salesWizardApi.save).mock.calls[0];
    expect(payload.attach_dismissal).toEqual({ reason: "Customer declined" });
  });

  it("retires a skip once the service is actually added", async () => {
    const { result } = renderHook(() => useSalesWizard("ws-1"), { wrapper });
    await waitFor(() => expect(result.current.attachWarning).not.toBeNull());
    act(() => result.current.dismissAttach("Customer declined"));

    // The rep adds the gutters after all, so the preview stops warning.
    previewReturns(null);
    act(() => result.current.addCharge());

    // Wait on the preview itself, not on `attachWarning` — that is already null
    // from the dismissal, so it cannot distinguish "skipped" from "satisfied".
    await waitFor(
      () => expect(result.current.document?.attach_warning).toBeNull(),
      { timeout: 2000 },
    );
    vi.mocked(salesWizardApi.save).mockResolvedValue({
      id: "q1",
    } as Awaited<ReturnType<typeof salesWizardApi.save>>);
    vi.mocked(salesWizardApi.send).mockResolvedValue({
      id: "q1",
    } as Awaited<ReturnType<typeof salesWizardApi.send>>);
    await act(async () => {
      await result.current.save();
    });

    // No phantom "they declined" on a quote that carries the add-on.
    const [, payload] = vi.mocked(salesWizardApi.save).mock.calls[0];
    expect(payload.attach_dismissal).toBeNull();
  });

  it("does not let a skip answer a different rule", async () => {
    const { result } = renderHook(() => useSalesWizard("ws-1"), { wrapper });
    await waitFor(() => expect(result.current.attachWarning).not.toBeNull());
    act(() => result.current.dismissAttach("Customer declined"));
    expect(result.current.attachWarning).toBeNull();

    // The quote becomes a siding job: a new rule, which the rep has not answered.
    previewReturns(
      warning({ primary_service: "siding", suggested_categories: ["trim"] }),
    );
    act(() => result.current.addCharge());

    await waitFor(() =>
      expect(result.current.attachWarning?.primary_service).toBe("siding"),
    );
  });
});
