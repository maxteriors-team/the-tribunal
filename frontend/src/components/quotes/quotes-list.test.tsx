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

const {
  listMock,
  deliverMock,
  recordDepositMock,
  sendMock,
  getMock,
  deleteMock,
  assignMock,
  useWorkspaceIdMock,
  toastMock,
} = vi.hoisted(() => ({
  listMock: vi.fn(),
  deliverMock: vi.fn(),
  recordDepositMock: vi.fn(),
  sendMock: vi.fn(),
  getMock: vi.fn(),
  deleteMock: vi.fn(),
  assignMock: vi.fn(),
  useWorkspaceIdMock: vi.fn(),
  toastMock: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/lib/api/quotes", () => ({
  quotesApi: {
    list: listMock,
    get: getMock,
    update: vi.fn(),
    delete: deleteMock,
    assign: assignMock,
    send: sendMock,
    deliver: deliverMock,
    recordDeposit: recordDepositMock,
    approve: vi.fn(),
    decline: vi.fn(),
  },
}));

vi.mock("sonner", () => ({ toast: toastMock }));

vi.mock("@/components/workspaces/team-member-picker", () => ({
  TeamMemberPicker: ({
    value,
    onValueChange,
    label,
  }: {
    value: number | null;
    onValueChange: (value: number | null) => void;
    label?: string;
  }) => (
    <label>
      {label}
      <select
        aria-label={label}
        value={value ?? ""}
        onChange={(event) => onValueChange(event.target.value ? Number(event.target.value) : null)}
      >
        <option value="">Unassigned</option>
        <option value="7">Morgan Manager</option>
      </select>
    </label>
  ),
}));

vi.mock("@/hooks/useWorkspaceId", () => ({
  useWorkspaceId: () => useWorkspaceIdMock(),
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

describe("QuotesList deposits", () => {
  const listOne = (overrides: Partial<Quote> = {}) =>
    listMock.mockResolvedValue({
      items: [quote(overrides)],
      total: 1,
      page: 1,
      page_size: 100,
      pages: 1,
    });

  it("offers manual recording for a due deposit and shows its amount", async () => {
    listOne({
      deposit_amount: 321,
      deposit_required: true,
      deposit_paid: false,
    });
    renderList();

    expect(await screen.findByText("Deposit due · $321.00")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Actions" }));
    expect(screen.getByRole("menuitem", { name: "Record deposit" })).toBeInTheDocument();
    expect(
      screen.getByRole("menuitem", { name: "Open customer payment page" }),
    ).toBeInTheDocument();
  });

  it("shows the recorded method and removes the action once paid", async () => {
    listOne({
      deposit_amount: 321,
      deposit_required: false,
      deposit_paid: true,
      deposit_paid_at: "2026-08-13T14:00:00Z",
      deposit_payment_method: "check",
    });
    renderList();

    expect(await screen.findByText("Deposit paid · Check")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Actions" }));
    expect(screen.queryByRole("menuitem", { name: "Record deposit" })).not.toBeInTheDocument();
  });
});

describe("QuotesList ownership", () => {
  const listOne = (overrides: Partial<Quote> = {}) =>
    listMock.mockResolvedValue({
      items: [quote(overrides)],
      total: 1,
      page: 1,
      page_size: 100,
      pages: 1,
    });

  it("shows the assigned sales owner", async () => {
    listOne({
      assigned_user_id: 4,
      assignee: { id: 4, full_name: "Avery Owner", email: "avery@example.com" },
    });

    renderList();

    expect(await screen.findByText("Avery Owner")).toBeInTheDocument();
    expect(screen.getByText("avery@example.com")).toBeInTheDocument();
  });

  it("reassigns an approved quote and keeps the action available", async () => {
    listOne({ status: "approved", assigned_user_id: null, assignee: null });
    assignMock.mockResolvedValue(
      quote({
        status: "approved",
        assigned_user_id: 7,
        assignee: { id: 7, full_name: "Morgan Manager", email: "morgan@example.com" },
      }),
    );

    renderList();
    await screen.findByText("QUO-000123");
    await userEvent.click(screen.getByRole("button", { name: "Actions" }));
    await userEvent.click(await screen.findByText("Assign owner"));
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Sales owner" }), "7");
    await userEvent.click(screen.getByRole("button", { name: "Save owner" }));

    await waitFor(() => expect(assignMock).toHaveBeenCalledWith("ws-1", "quote-1", 7));
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

    await waitFor(() => expect(deliverMock).toHaveBeenCalledWith("ws-1", "quote-1", "email"));
    // The address the server actually resolved, not the one the rep assumed.
    expect(toastMock.success).toHaveBeenCalledWith("Proposal emailed to jo@example.com");
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

    await waitFor(() => expect(deliverMock).toHaveBeenCalledWith("ws-1", "quote-1", "sms"));
    expect(toastMock.success).toHaveBeenCalledWith("Proposal texted to +15551234567");
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

    expect(await screen.findByText("Email proposal to client")).toBeInTheDocument();
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

/**
 * Editing and deleting after the quote is out the door.
 *
 * "Sent" is not a lock: the customer asked for a change, or the quote should
 * never have gone out at all. What must stay locked is a *decided* quote —
 * approved, declined or expired — because the service refuses those, and a menu
 * item that only ever produces a 409 is worse than no menu item.
 */
describe("QuotesList editing and deleting", () => {
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

  it("opens the quote editor when its number is clicked", async () => {
    listOne({ status: "sent" });
    getMock.mockResolvedValue(quote({ status: "sent" }));
    renderList();

    await userEvent.click(await screen.findByRole("button", { name: "QUO-000123" }));

    expect(
      await screen.findByRole("heading", { name: "Edit quote QUO-000123" }),
    ).toBeInTheDocument();
    await waitFor(() => expect(getMock).toHaveBeenCalledWith("ws-1", "quote-1"));
  });

  it("offers edit and delete on a quote the customer already has", async () => {
    listOne({ status: "sent" });

    await openMenu();

    expect(await screen.findByText("Edit basic details")).toBeInTheDocument();
    expect(screen.getByText("Delete quote")).toBeInTheDocument();
  });

  it("warns that deleting a sent quote kills the customer's link", async () => {
    // The proposal URL is already in someone's inbox; deleting it turns that
    // link into a dead page, which is not what "delete" implies on a draft.
    listOne({ status: "sent" });

    await openMenu();
    await userEvent.click(await screen.findByText("Delete quote"));

    expect(
      await screen.findByText(/breaks the proposal link the customer has/i),
    ).toBeInTheDocument();
  });

  it("keeps the plain-draft wording when nothing was ever sent", async () => {
    listOne({ status: "draft", public_token: null });

    await openMenu();
    await userEvent.click(await screen.findByText("Delete quote"));

    expect(await screen.findByText(/never been sent/i)).toBeInTheDocument();
  });

  it("deletes only after the confirmation is accepted", async () => {
    listOne({ status: "sent" });
    deleteMock.mockResolvedValue(undefined);

    await openMenu();
    await userEvent.click(await screen.findByText("Delete quote"));
    expect(deleteMock).not.toHaveBeenCalled();

    await userEvent.click(await screen.findByRole("button", { name: "Delete quote" }));

    await waitFor(() => expect(deleteMock).toHaveBeenCalledWith("ws-1", "quote-1"));
    expect(toastMock.success).toHaveBeenCalledWith("Quote QUO-000123 deleted");
  });

  it("surfaces the server's refusal instead of a success toast", async () => {
    listOne({ status: "sent" });
    deleteMock.mockRejectedValue({
      response: { status: 409, data: { detail: "Cannot delete a approved quote" } },
    });

    await openMenu();
    await userEvent.click(await screen.findByText("Delete quote"));
    await userEvent.click(await screen.findByRole("button", { name: "Delete quote" }));

    await waitFor(() => expect(toastMock.error).toHaveBeenCalled());
    expect(toastMock.success).not.toHaveBeenCalled();
  });

  it("hides both once the quote is decided, matching the service's own lock", async () => {
    listOne({ status: "approved" });

    await openMenu();
    await screen.findByText("Preview client proposal");

    expect(screen.queryByText("Edit basic details")).not.toBeInTheDocument();
    expect(screen.queryByText("Delete quote")).not.toBeInTheDocument();
  });
});
