/**
 * The quotes list is where the "your client is reading it right now" signal
 * has to land, and where staff previews must NOT be mistaken for client views.
 * Both are easy to break silently, so both are pinned here.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { QuotesList } from "@/components/quotes/quotes-list";
import type { Quote } from "@/types";

const { listMock, pushMock, useWorkspaceIdMock } = vi.hoisted(() => ({
  listMock: vi.fn(),
  pushMock: vi.fn(),
  useWorkspaceIdMock: vi.fn(),
}));

vi.mock("@/lib/api/quotes", () => ({
  quotesApi: {
    list: listMock,
    send: vi.fn(),
    approve: vi.fn(),
    decline: vi.fn(),
  },
}));

vi.mock("@/hooks/useWorkspaceId", () => ({
  useWorkspaceId: () => useWorkspaceIdMock(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

function quote(overrides: Partial<Quote> = {}): Quote {
  return {
    id: "quote-1",
    workspace_id: "ws-1",
    number: "QUO-000123",
    title: "Backyard lighting install",
    status: "sent",
    subtotal: 1070,
    tax_amount: 0,
    discount_amount: 0,
    total: 1070,
    currency: "USD",
    public_token: "tok-abc",
    created_at: "2026-07-01T00:00:00Z",
    updated_at: "2026-07-01T00:00:00Z",
    ...overrides,
  };
}

function renderList() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  render(
    <QueryClientProvider client={client}>
      <QuotesList />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  useWorkspaceIdMock.mockReturnValue("ws-1");
});

describe("QuotesList client-view signal", () => {
  it("shows when the client last opened the proposal", async () => {
    const tenMinutesAgo = new Date(Date.now() - 10 * 60 * 1000).toISOString();
    listMock.mockResolvedValue({
      items: [
        quote({
          first_viewed_at: tenMinutesAgo,
          last_viewed_at: tenMinutesAgo,
          view_count: 1,
        }),
      ],
      total: 1,
      page: 1,
      page_size: 100,
      pages: 1,
    });

    renderList();

    expect(await screen.findByText(/^Viewed .*ago$/)).toBeInTheDocument();
  });

  it("stays quiet for a quote no client has opened", async () => {
    listMock.mockResolvedValue({
      items: [quote()],
      total: 1,
      page: 1,
      page_size: 100,
      pages: 1,
    });

    renderList();

    expect(await screen.findByText("QUO-000123")).toBeInTheDocument();
    expect(screen.queryByText(/^Viewed /)).not.toBeInTheDocument();
  });
});

describe("QuotesList client proposal links", () => {
  it("flags the staff preview so it is not counted as a client view", async () => {
    const openSpy = vi.fn();
    vi.stubGlobal("open", openSpy);
    listMock.mockResolvedValue({
      items: [quote()],
      total: 1,
      page: 1,
      page_size: 100,
      pages: 1,
    });

    renderList();
    await screen.findByText("QUO-000123");

    await userEvent.click(screen.getByRole("button", { name: "Actions" }));
    await userEvent.click(await screen.findByText("Preview client proposal"));

    await waitFor(() => expect(openSpy).toHaveBeenCalled());
    expect(openSpy.mock.calls[0][0]).toContain("/p/quotes/tok-abc?preview=1");
    vi.unstubAllGlobals();
  });

  it("copies the customer link without the preview flag", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    listMock.mockResolvedValue({
      items: [quote()],
      total: 1,
      page: 1,
      page_size: 100,
      pages: 1,
    });

    renderList();
    await screen.findByText("QUO-000123");

    await userEvent.click(screen.getByRole("button", { name: "Actions" }));
    await userEvent.click(await screen.findByText("Copy client link"));

    await waitFor(() => expect(writeText).toHaveBeenCalled());
    const copied = writeText.mock.calls[0][0] as string;
    expect(copied).toContain("/p/quotes/tok-abc");
    expect(copied).not.toContain("preview");
  });
});
