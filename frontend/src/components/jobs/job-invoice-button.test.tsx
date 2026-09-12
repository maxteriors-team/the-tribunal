/**
 * Billing a job from the job screen.
 *
 * The operator finishes a job, adjusts the priced scope, and invoices it without
 * leaving the tab. The guards are the point: the server bills the job's *saved*
 * pricing, so invoicing with unsaved edits would produce an invoice that differs
 * from what is on screen, and a job that already has an invoice must not get a
 * second one.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { JobVisitsPricing } from "@/components/jobs/job-visits-pricing";
import type { JobPricing, JobStatus } from "@/lib/api/jobs";

const { getPricingMock, listVisitsMock, createInvoiceMock, replacePricingMock, toastMock } =
  vi.hoisted(() => ({
    getPricingMock: vi.fn(),
    listVisitsMock: vi.fn(),
    createInvoiceMock: vi.fn(),
    replacePricingMock: vi.fn(),
    toastMock: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
  }));

vi.mock("@/lib/api/jobs", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/jobs")>("@/lib/api/jobs");
  return {
    ...actual,
    jobsApi: {
      ...actual.jobsApi,
      getPricing: getPricingMock,
      listVisits: listVisitsMock,
      createInvoice: createInvoiceMock,
      replacePricing: replacePricingMock,
    },
  };
});

vi.mock("sonner", () => ({ toast: toastMock }));

const PRICING: JobPricing = {
  job_id: "job-1",
  tax_rate: "0.00",
  items: [
    {
      id: "li-1",
      name: "Gutter clearing",
      description: null,
      quantity: "2.00",
      unit_price: "150.00",
      taxable: true,
      position: 0,
      total: "300.00",
    },
  ],
  subtotal: "300.00",
  discount: "0.00",
  tax: "0.00",
  total: "300.00",
} as unknown as JobPricing;

async function renderPanel({
  jobStatus = "completed" as JobStatus,
  invoiceId = null as string | null,
  pricing = PRICING,
}: { jobStatus?: JobStatus; invoiceId?: string | null; pricing?: JobPricing } = {}) {
  getPricingMock.mockResolvedValue(pricing);
  listVisitsMock.mockResolvedValue([]);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <JobVisitsPricing
        workspaceId="ws-1"
        jobId="job-1"
        canViewPricing
        canEditPricing
        jobStatus={jobStatus}
        invoiceId={invoiceId}
      />
    </QueryClientProvider>,
  );
  // Wait for pricing to resolve, not merely for the section heading: the totals
  // row renders only once the query settles, and asserting before that races.
  await screen.findByText("Subtotal");
}

beforeEach(() => vi.clearAllMocks());

describe("creating an invoice from a job", () => {
  it("bills a completed job and reports the new invoice", async () => {
    createInvoiceMock.mockResolvedValue({ id: "inv-1", number: "INV-0007" });
    await renderPanel();

    await userEvent.click(await screen.findByRole("button", { name: "Create invoice" }));

    await waitFor(() => expect(createInvoiceMock).toHaveBeenCalledWith("ws-1", "job-1", {}));
    await waitFor(() =>
      expect(toastMock.success).toHaveBeenCalledWith(
        "Invoice INV-0007 created as a draft",
        expect.anything(),
      ),
    );
  });

  it("surfaces the server's refusal rather than a generic failure", async () => {
    createInvoiceMock.mockRejectedValue({
      response: { data: { detail: "This job is already linked to an invoice" } },
    });
    await renderPanel();

    await userEvent.click(await screen.findByRole("button", { name: "Create invoice" }));

    await waitFor(() =>
      expect(toastMock.error).toHaveBeenCalledWith("This job is already linked to an invoice"),
    );
  });
});

describe("when billing is not offered", () => {
  it.each<JobStatus>(["scheduled", "in_progress", "unscheduled", "cancelled"])(
    "hides the button for a %s job",
    async (jobStatus) => {
      await renderPanel({ jobStatus });

      expect(screen.queryByRole("button", { name: "Create invoice" })).toBeNull();
    },
  );

  it("replaces the button with a note once the job has been invoiced", async () => {
    await renderPanel({ invoiceId: "inv-1" });

    expect(screen.queryByRole("button", { name: "Create invoice" })).toBeNull();
    expect(screen.getByText(/Invoiced\./)).toBeVisible();
  });
});

describe("guards against billing the wrong amount", () => {
  it("blocks invoicing while pricing edits are unsaved", async () => {
    await renderPanel();
    // Editing the quantity puts the panel in a dirty state; the on-screen total
    // now differs from what the server would bill.
    await userEvent.clear(screen.getByLabelText("Line 1 quantity"));
    await userEvent.type(screen.getByLabelText("Line 1 quantity"), "5");

    expect(screen.getByRole("button", { name: "Create invoice" })).toBeDisabled();
    expect(createInvoiceMock).not.toHaveBeenCalled();
  });

  it("blocks invoicing a job with no priced scope", async () => {
    await renderPanel({
      pricing: {
        ...PRICING,
        items: [],
        subtotal: "0.00",
        total: "0.00",
      } as unknown as JobPricing,
    });

    expect(screen.getByRole("button", { name: "Create invoice" })).toBeDisabled();
  });
});
