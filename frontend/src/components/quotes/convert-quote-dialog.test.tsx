import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConvertQuoteDialog } from "@/components/quotes/convert-quote-dialog";
import type { Quote } from "@/types";

const { convertMock, rosterMock, crewsMock, toastMock } = vi.hoisted(() => ({
  convertMock: vi.fn(),
  rosterMock: vi.fn(),
  crewsMock: vi.fn(),
  toastMock: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/lib/api/quotes", () => ({ quotesApi: { convert: convertMock } }));
vi.mock("@/hooks/useJobs", () => ({
  useWorkspaceTechnicians: () => rosterMock(),
  useWorkspaceCrews: () => crewsMock(),
}));
vi.mock("sonner", () => ({ toast: toastMock }));

const baseQuote: Quote = {
  id: "quote-1",
  workspace_id: "ws-1",
  number: "QUO-000123",
  title: "Landscape installation",
  status: "approved",
  subtotal: 500,
  tax_amount: 0,
  discount_amount: 0,
  total: 500,
  currency: "USD",
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

function renderDialog(quote: Quote = baseQuote) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <ConvertQuoteDialog workspaceId="ws-1" quote={quote} open onOpenChange={vi.fn()} />
    </QueryClientProvider>,
  );
}

async function setWindow() {
  await userEvent.type(screen.getByLabelText("Scheduled start"), "2026-12-01T09:00");
  await userEvent.type(screen.getByLabelText("Scheduled end"), "2026-12-01T12:00");
}

beforeEach(() => {
  vi.clearAllMocks();
  rosterMock.mockReturnValue({
    data: { items: [{ id: "tech-1", name: "Alex Field", color: "#0ea5e9", user_id: 11 }] },
  });
  crewsMock.mockReturnValue({
    data: { items: [{ id: "crew-1", name: "Install Crew", is_active: true }] },
  });
  convertMock.mockResolvedValue({
    quote: baseQuote,
    job_id: "job-1",
    invoice_id: "invoice-1",
    idempotent_replay: false,
    crew_notification: {
      status: "sent",
      recipient_count: 1,
      sent_count: 1,
      failed_count: 0,
    },
  });
});

describe("ConvertQuoteDialog guided closeout", () => {
  it("shows no-deposit state and requires a complete installation window", async () => {
    renderDialog({ ...baseQuote, deposit_required: false, deposit_paid: false });
    expect(screen.getByText("No deposit required")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Schedule installation" })).toBeDisabled();

    await setWindow();
    expect(screen.getByRole("button", { name: "Schedule installation" })).toBeEnabled();
  });

  it("blocks unpaid required deposit until explicit confirmation", async () => {
    renderDialog({
      ...baseQuote,
      public_token: "public-token",
      deposit_amount: 125,
      deposit_required: true,
      deposit_paid: false,
    });
    expect(screen.getByText(/Due · \$125\.00/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open customer payment page/ })).toHaveAttribute(
      "href",
      "/p/quotes/public-token",
    );
    await setWindow();
    expect(screen.getByRole("button", { name: "Schedule installation" })).toBeDisabled();
    await userEvent.click(screen.getByLabelText(/Schedule with the required deposit still unpaid/));
    expect(screen.getByRole("button", { name: "Schedule installation" })).toBeEnabled();
  });

  it("submits crew, technicians, schedule, and reports authoritative delivery", async () => {
    renderDialog({
      ...baseQuote,
      lighting_project_id: "project-1",
      deposit_amount: 125,
      deposit_required: false,
      deposit_paid: true,
      deposit_paid_at: "2026-08-12T15:00:00Z",
    });
    expect(screen.getByText(/Paid/)).toBeInTheDocument();
    await setWindow();
    await userEvent.selectOptions(screen.getByLabelText("Route to crew"), "crew-1");
    await userEvent.click(screen.getByText("Alex Field"));
    await userEvent.click(screen.getByRole("button", { name: "Schedule installation" }));

    await waitFor(() =>
      expect(convertMock).toHaveBeenCalledWith(
        "ws-1",
        "quote-1",
        expect.objectContaining({
          crew_id: "crew-1",
          technician_ids: ["tech-1"],
          confirm_unpaid_deposit: false,
        }),
      ),
    );
    expect(await screen.findByText(/Crew delivery: sent · 1\/1 recipients/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open job/ })).toHaveAttribute(
      "href",
      "/jobs?job=job-1",
    );
    expect(screen.getByRole("link", { name: /Open invoice/ })).toHaveAttribute(
      "href",
      "/invoices/invoice-1",
    );
  });

  it("preserves invoice-only conversion without a schedule", async () => {
    renderDialog();
    await userEvent.click(screen.getByLabelText("Create a field-service job"));
    await userEvent.click(screen.getByRole("button", { name: "Schedule installation" }));
    await waitFor(() =>
      expect(convertMock).toHaveBeenCalledWith(
        "ws-1",
        "quote-1",
        expect.objectContaining({ create_job: false, scheduled_start: null, scheduled_end: null }),
      ),
    );
  });
});
