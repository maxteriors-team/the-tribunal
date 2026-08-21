import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CopyToJobTab } from "@/components/quotes/copy-to-job-tab";
import type { Quote } from "@/types";

const { listMock } = vi.hoisted(() => ({ listMock: vi.fn() }));

vi.mock("@/hooks/useWorkspaceId", () => ({ useWorkspaceId: () => "ws-1" }));
vi.mock("@/lib/api/quotes", () => ({ quotesApi: { list: listMock } }));
vi.mock("@/components/quotes/convert-quote-dialog", () => ({
  ConvertQuoteDialog: ({ quote, mode }: { quote: Quote | null; mode?: string }) =>
    quote ? <div data-testid="copy-dialog">{`${quote.number}:${mode}`}</div> : null,
}));

const quote = (overrides: Partial<Quote>): Quote => ({
  id: "quote-1",
  workspace_id: "ws-1",
  number: "QUO-000123",
  title: "Front walk lighting",
  notes: "Install path lights along the front walk.",
  status: "approved",
  subtotal: 500,
  tax_amount: 0,
  discount_amount: 0,
  total: 500,
  currency: "USD",
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
  ...overrides,
});

function renderTab() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <CopyToJobTab />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  listMock.mockResolvedValue({
    items: [
      quote({
        lighting_project_id: "project-1",
        selected_permanent_kits: [
          { feet: 400, quantity: 1 },
          { feet: 100, quantity: 2 },
        ],
      }),
      quote({
        id: "quote-2",
        number: "QUO-000124",
        title: "Back patio lighting",
        converted_job_id: "job-2",
      }),
    ],
    total: 2,
    page: 1,
    page_size: 500,
    has_next: false,
  });
});

describe("CopyToJobTab", () => {
  it("lists approved work and opens the job-only handoff", async () => {
    renderTab();

    expect((await screen.findAllByText("Front walk lighting"))[0]).toBeVisible();
    expect(screen.getAllByText("Install path lights along the front walk.").length).toBeGreaterThan(
      1,
    );
    expect(screen.getAllByText("Included")[0]).toBeVisible();
    expect(screen.getAllByText("1 × 400-ft kit")).toHaveLength(2);
    expect(screen.getAllByText("2 × 100-ft kit")).toHaveLength(2);
    expect(screen.getAllByRole("link", { name: /Open job/ })[0]).toHaveAttribute(
      "href",
      "/calendar?job=job-2",
    );
    await waitFor(() =>
      expect(listMock).toHaveBeenCalledWith("ws-1", { page_size: 500, status: "approved" }),
    );

    await userEvent.click(screen.getAllByRole("button", { name: "Copy to job" })[0]);
    expect(screen.getByTestId("copy-dialog")).toHaveTextContent("QUO-000123:copy-to-job");
  });

  it("explains that approval is required when nothing is ready", async () => {
    listMock.mockResolvedValueOnce({ items: [], total: 0 });
    renderTab();

    expect(await screen.findByText("No approved estimates or quotes")).toBeVisible();
    expect(screen.getByText(/Approve an estimate in the Quotes tab/)).toBeVisible();
  });
});
