import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConvertQuoteDialog } from "@/components/quotes/convert-quote-dialog";
import type { Quote } from "@/types";

const { convertMock, rosterMock, toastMock } = vi.hoisted(() => ({
  convertMock: vi.fn(),
  rosterMock: vi.fn(),
  toastMock: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/lib/api/quotes", () => ({
  quotesApi: { convert: convertMock },
}));

vi.mock("@/hooks/useJobs", () => ({
  useWorkspaceTechnicians: () => rosterMock(),
}));

vi.mock("sonner", () => ({ toast: toastMock }));

const quote: Quote = {
  id: "quote-1",
  workspace_id: "ws-1",
  number: "QUO-000123",
  title: "Roof cleaning",
  status: "approved",
  subtotal: 500,
  tax_amount: 0,
  discount_amount: 0,
  total: 500,
  currency: "USD",
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

function renderDialog() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <ConvertQuoteDialog
        workspaceId="ws-1"
        quote={quote}
        open
        onOpenChange={vi.fn()}
      />
    </QueryClientProvider>,
  );
}

describe("ConvertQuoteDialog field crew", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    rosterMock.mockReturnValue({
      data: {
        items: [
          {
            id: "tech-1",
            name: "Alex Field",
            color: "#0ea5e9",
            user_id: 11,
          },
        ],
      },
      isPending: false,
      isError: false,
      refetch: vi.fn(),
    });
    convertMock.mockResolvedValue({
      quote,
      job_id: "job-1",
      invoice_id: "invoice-1",
    });
  });

  it("submits selected technicians with the conversion", async () => {
    renderDialog();

    await userEvent.click(screen.getByText("Alex Field"));
    await userEvent.click(screen.getByRole("button", { name: "Convert" }));

    await waitFor(() =>
      expect(convertMock).toHaveBeenCalledWith(
        "ws-1",
        "quote-1",
        expect.objectContaining({ technician_ids: ["tech-1"] }),
      ),
    );
  });

  it("keeps an empty crew valid for the dispatch queue", async () => {
    renderDialog();

    await userEvent.click(screen.getByRole("button", { name: "Convert" }));

    await waitFor(() =>
      expect(convertMock).toHaveBeenCalledWith(
        "ws-1",
        "quote-1",
        expect.objectContaining({ technician_ids: [] }),
      ),
    );
  });
});
