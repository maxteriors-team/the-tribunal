/**
 * The view beacon is the whole point of the tracking feature, and it has two
 * ways to be wrong that no type check catches: firing more than once per visit,
 * and firing on a staff preview (which would alert an operator about their own
 * click). Both are pinned here.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Suspense } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import PublicProposalPage from "@/app/p/quotes/[token]/page";
import type { PublicProposal } from "@/types/proposal";

const { approveMock, depositCheckoutMock, getMock, recordViewMock } = vi.hoisted(() => ({
  approveMock: vi.fn(),
  depositCheckoutMock: vi.fn(),
  getMock: vi.fn(),
  recordViewMock: vi.fn(),
}));

vi.mock("@/lib/api/public-proposals", () => ({
  publicProposalsApi: {
    get: getMock,
    recordView: recordViewMock,
    approve: approveMock,
    decline: vi.fn(),
    depositCheckout: depositCheckoutMock,
    depositStatus: vi.fn(),
  },
}));

function proposal(): PublicProposal {
  return {
    token: "tok-abc",
    number: "QUO-000123",
    title: "Backyard lighting install",
    status: "sent",
    proposal_version: 1,
    currency: "USD",
    subtotal: 1070,
    tax_amount: 0,
    discount_amount: 0,
    total: 1070,
    is_expired: false,
    is_decided: false,
    line_items: [
      {
        name: "Fixtures",
        description: null,
        quantity: 6,
        unit_price: 120,
        discount: 0,
        total: 720,
      },
    ],
    packages: [],
    deposit_paid: false,
    branding: {
      business_name: "Maxteriors Lighting",
      brand_color: "#0A7C3A",
      accent_color: "#C9A227",
    },
  };
}

async function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  // `use(params)` suspends on first render; Next supplies the boundary in the
  // real app, and the awaited `act` lets it resolve before assertions run.
  await act(async () => {
    render(
      <QueryClientProvider client={client}>
        <Suspense fallback={null}>
          <PublicProposalPage params={Promise.resolve({ token: "tok-abc" })} />
        </Suspense>
      </QueryClientProvider>,
    );
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  getMock.mockResolvedValue(proposal());
  recordViewMock.mockResolvedValue(undefined);
  approveMock.mockResolvedValue({
    token: "tok-abc",
    status: "approved",
    message: "Thank you",
    deposit_required: false,
  });
  window.history.replaceState({}, "", "/p/quotes/tok-abc");
});

describe("public proposal view beacon", () => {
  it("records exactly one view when a client opens the page", async () => {
    await renderPage();

    await screen.findByText("Proposal QUO-000123");
    await waitFor(() => expect(recordViewMock).toHaveBeenCalledTimes(1));
    expect(recordViewMock).toHaveBeenCalledWith("tok-abc");
  });

  it("stays silent for a staff preview so the operator is not alerted by their own click", async () => {
    window.history.replaceState({}, "", "/p/quotes/tok-abc?preview=1");

    await renderPage();

    await screen.findByText("Proposal QUO-000123");
    expect(recordViewMock).not.toHaveBeenCalled();
  });

  it("submits the exact rendered proposal version on keyboard approval", async () => {
    const user = userEvent.setup();
    await renderPage();
    const approve = await screen.findByRole("button", {
      name: /Approve Proposal/,
    });

    approve.focus();
    await user.keyboard("{Enter}");

    await waitFor(() => expect(approveMock).toHaveBeenCalledWith("tok-abc", 1, null));
  });
});

const GREEN_SKY_DOCUMENT = {
  version: 1,
  service: "permanent",
  client: { first_name: "Dana", last_name: "Homeowner" },
  tier_order: [],
  tiers: [],
  additional_charges: [],
  category_sections: [
    {
      key: "permanent",
      label: "Permanent Lighting",
      lines: [],
      value_props: [],
      financed_total: 1070,
      cash_total: 1070,
      cash_savings: 0,
      monthly_payment: 0,
      min_applied: false,
      takedown: false,
      storage: false,
    },
  ],
  mockups: [],
  green_sky: {
    application_url: "https://projects.greensky.com/applyshort",
    merchant_number: "1234567890",
    plan_number: "246810",
    apr_percent: 0,
    term_months: 24,
    offer_details: "Provider-approved 0% APR for 24 months.",
    disclosure:
      "Financing is subject to credit approval and the terms in your GreenSky loan documents. Applying does not accept this proposal, reserve an installation date, or guarantee approval. GreenSky Servicing, LLC is a financial technology company, not a lender. Program lenders determine credit approval and loan terms.",
  },
};

describe("public proposal approval payment routing", () => {
  it("keeps a GreenSky-enabled approval on the proposal", async () => {
    const user = userEvent.setup();
    getMock.mockResolvedValue({
      ...proposal(),
      deposit_required: true,
      deposit_amount: 214,
      proposal_document: GREEN_SKY_DOCUMENT,
    });
    approveMock.mockResolvedValue({
      token: "tok-abc",
      status: "approved",
      message: "Thank you",
      deposit_required: true,
    });

    await renderPage();
    await user.click(await screen.findByRole("button", { name: "Accept proposal" }));

    await waitFor(() => expect(approveMock).toHaveBeenCalledWith("tok-abc", 1, null));
    expect(depositCheckoutMock).not.toHaveBeenCalled();
    expect(await screen.findByText(/thank you, dana/i)).toBeVisible();
    expect(screen.getByRole("button", { name: "Pay Deposit" })).toBeVisible();
  });

  it("preserves automatic Stripe checkout for legacy deposit approvals", async () => {
    const user = userEvent.setup();
    getMock.mockResolvedValue({
      ...proposal(),
      deposit_required: true,
      deposit_amount: 214,
      deposit_percentage: 20,
    });
    approveMock.mockResolvedValue({
      token: "tok-abc",
      status: "approved",
      message: "Thank you",
      deposit_required: true,
    });
    depositCheckoutMock.mockImplementation(() => new Promise(() => undefined));

    await renderPage();
    await user.click(await screen.findByRole("button", { name: /approve & pay deposit/i }));

    await waitFor(() => expect(depositCheckoutMock).toHaveBeenCalledWith("tok-abc"));
  });
});
