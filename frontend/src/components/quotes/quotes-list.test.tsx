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

const { listMock, deliverMock, sendMock, pushMock, useWorkspaceIdMock, toastMock } =
  vi.hoisted(() => ({
    listMock: vi.fn(),
    deliverMock: vi.fn(),
    sendMock: vi.fn(),
    pushMock: vi.fn(),
    useWorkspaceIdMock: vi.fn(),
    toastMock: { success: vi.fn(), error: vi.fn() },
  }));

vi.mock("@/lib/api/quotes", () => ({
  quotesApi: {
    list: listMock,
    send: sendMock,
    deliver: deliverMock,
    approve: vi.fn(),
    decline: vi.fn(),
  },
}));

vi.mock("sonner", () => ({ toast: toastMock }));

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

/**
 * Emailing and texting the proposal. The rep's whole question is "did it
 * actually reach them?", so these pin the channel, the confirmed destination,
 * and — most importantly — that a refusal surfaces the server's reason instead
 * of a cheerful success toast.
 */
describe("QuotesList proposal delivery", () => {
  const listOne = (overrides: Partial<Quote> = {}) =>
    listMock.mockResolvedValue({
      items: [quote(overrides)],
      total: 1,
      page: 1,
      page_size: 100,
      pages: 1,
    });

  const openMenu = async () => {
    renderList();
    await screen.findByText("QUO-000123");
    await userEvent.click(screen.getByRole("button", { name: "Actions" }));
  };

  it("emails the proposal and confirms where it went", async () => {
    listOne();
    deliverMock.mockResolvedValue({
      ok: true,
      channel: "email",
      to: "jo@example.com",
    });

    await openMenu();
    await userEvent.click(await screen.findByText("Email proposal to client"));

    await waitFor(() =>
      expect(deliverMock).toHaveBeenCalledWith("ws-1", "quote-1", "email"),
    );
    // The address the server actually resolved, not the one the rep assumed.
    expect(toastMock.success).toHaveBeenCalledWith(
      "Proposal emailed to jo@example.com",
    );
  });

  it("texts the proposal and confirms the number", async () => {
    listOne();
    deliverMock.mockResolvedValue({
      ok: true,
      channel: "sms",
      to: "+15551234567",
    });

    await openMenu();
    await userEvent.click(await screen.findByText("Text proposal to client"));

    await waitFor(() =>
      expect(deliverMock).toHaveBeenCalledWith("ws-1", "quote-1", "sms"),
    );
    expect(toastMock.success).toHaveBeenCalledWith(
      "Proposal texted to +15551234567",
    );
  });

  it("surfaces the server's reason when a text can't go out", async () => {
    // "This number has opted out" is something the rep can act on right now;
    // a generic "failed to send" is the message that loses the sale.
    listOne();
    deliverMock.mockRejectedValue({
      response: {
        status: 400,
        data: { detail: "No client phone on this proposal — add one." },
      },
    });

    await openMenu();
    await userEvent.click(await screen.findByText("Text proposal to client"));

    await waitFor(() => expect(toastMock.error).toHaveBeenCalled());
    expect(toastMock.error.mock.calls[0][0]).toContain("No client phone");
    expect(toastMock.success).not.toHaveBeenCalled();
  });

  it("offers delivery straight from a draft, with no send-first two-step", async () => {
    // The server marks the quote sent and mints its link on the way out, so
    // making the rep press "mark as sent" first would be busywork.
    listOne({ status: "draft", public_token: null });

    await openMenu();

    expect(
      await screen.findByText("Email proposal to client"),
    ).toBeInTheDocument();
    expect(screen.getByText("Text proposal to client")).toBeInTheDocument();
  });

  it("keeps the bookkeeping-only action distinct from actually sending", async () => {
    // `send` marks sent and emails best-effort — it reports success even when
    // nobody was emailed — so it must not be labelled as if it delivers.
    listOne({ status: "draft", public_token: null });

    await openMenu();

    expect(await screen.findByText("Mark as sent")).toBeInTheDocument();
    expect(screen.queryByText("Send quote")).not.toBeInTheDocument();
  });

  it("hides delivery once a quote is settled", async () => {
    // An approved quote is signed; re-texting a proposal link is not a thing
    // the rep should be one misclick away from.
    listOne({ status: "approved" });

    await openMenu();
    await screen.findByText("Preview client proposal");

    expect(screen.queryByText("Email proposal to client")).not.toBeInTheDocument();
    expect(screen.queryByText("Text proposal to client")).not.toBeInTheDocument();
  });
});
