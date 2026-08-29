import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConvertQuoteDialog } from "@/components/quotes/convert-quote-dialog";
import type { Quote } from "@/types";

const { canMock, convertMock, crewsMock, listQuoteImagesMock, rosterMock, toastMock } = vi.hoisted(
  () => ({
    canMock: vi.fn(),
    convertMock: vi.fn(),
    crewsMock: vi.fn(),
    listQuoteImagesMock: vi.fn(),
    rosterMock: vi.fn(),
    toastMock: { success: vi.fn(), error: vi.fn() },
  }),
);

vi.mock("@/lib/api/quotes", () => ({ quotesApi: { convert: convertMock } }));
vi.mock("@/lib/api/handoff-images", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/handoff-images")>();
  return { ...actual, listQuoteHandoffImages: listQuoteImagesMock };
});
vi.mock("@/hooks/useCapabilities", () => ({
  useCapabilities: () => ({ can: canMock }),
}));
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

function renderDialog(quote: Quote = baseQuote, mode: "closeout" | "copy-to-job" = "closeout") {
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
        mode={mode}
      />
    </QueryClientProvider>,
  );
}

async function setWindow() {
  await userEvent.type(screen.getByLabelText("Scheduled start"), "2026-12-01T09:00");
  await userEvent.type(screen.getByLabelText("Scheduled end"), "2026-12-01T12:00");
}

beforeEach(() => {
  vi.clearAllMocks();
  canMock.mockReturnValue(true);
  rosterMock.mockReturnValue({
    data: { items: [{ id: "tech-1", name: "Alex Field", color: "#0ea5e9", user_id: 11 }] },
  });
  crewsMock.mockReturnValue({
    data: { items: [{ id: "crew-1", name: "Install Crew", is_active: true }] },
  });
  listQuoteImagesMock.mockResolvedValue({
    images: [],
    max_images: 10,
    max_image_bytes: 10 * 1024 * 1024,
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

  it("shows editable handoff images before crew routing", async () => {
    renderDialog();

    const handoff = await screen.findByRole("heading", { name: "Field handoff images" });
    const crew = screen.getByRole("heading", { name: "Crew and members" });
    expect(handoff.compareDocumentPosition(crew) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    await waitFor(() => expect(screen.getByRole("button", { name: "Add images" })).toBeEnabled());
    expect(listQuoteImagesMock).toHaveBeenCalledWith("ws-1", "quote-1");
  });

  it("schedules without an invoice when billing access is unavailable", async () => {
    canMock.mockReturnValue(false);
    renderDialog();

    expect(screen.queryByLabelText("Create an invoice")).not.toBeInTheDocument();
    expect(screen.getByText(/Billing access is required to create an invoice/)).toBeVisible();

    await setWindow();
    await userEvent.click(screen.getByRole("button", { name: "Schedule installation" }));

    await waitFor(() =>
      expect(convertMock).toHaveBeenCalledWith(
        "ws-1",
        "quote-1",
        expect.objectContaining({ create_job: true, create_invoice: false }),
      ),
    );
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
    // The schedule is one surface; `/calendar?job=` opens the new job's detail
    // dialog directly instead of bouncing through the retired `/jobs` redirect.
    expect(screen.getByRole("link", { name: /Open job/ })).toHaveAttribute(
      "href",
      "/calendar?job=job-1",
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

  it("copies the description and layout into a job without creating an invoice by default", async () => {
    renderDialog(
      {
        ...baseQuote,
        notes: "Install path lights along the front walk.",
        lighting_project_id: "project-1",
      },
      "copy-to-job",
    );

    expect(screen.getByRole("heading", { name: "Copy quote QUO-000123 to a job" })).toBeVisible();
    expect(screen.getByText("Install path lights along the front walk.")).toBeVisible();
    expect(screen.getByText("Linked layout included")).toBeVisible();
    expect(screen.queryByLabelText("Create a field-service job")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Also create an invoice")).not.toBeChecked();

    await setWindow();
    await userEvent.click(screen.getByText("Alex Field"));
    await userEvent.click(screen.getByRole("button", { name: "Copy to job" }));

    await waitFor(() =>
      expect(convertMock).toHaveBeenCalledWith(
        "ws-1",
        "quote-1",
        expect.objectContaining({
          create_job: true,
          create_invoice: false,
          technician_ids: ["tech-1"],
        }),
      ),
    );
  });

  it("keeps an existing invoice linked when adding the missing job", async () => {
    canMock.mockReturnValue(false);
    renderDialog({ ...baseQuote, converted_invoice_id: "invoice-1" }, "copy-to-job");

    expect(screen.getByText("The existing invoice will stay linked to this job.")).toBeVisible();
    expect(screen.queryByLabelText("Also create an invoice")).not.toBeInTheDocument();

    await setWindow();
    await userEvent.click(screen.getByRole("button", { name: "Copy to job" }));

    await waitFor(() =>
      expect(convertMock).toHaveBeenCalledWith(
        "ws-1",
        "quote-1",
        expect.objectContaining({ create_job: true, create_invoice: true }),
      ),
    );
  });
});
