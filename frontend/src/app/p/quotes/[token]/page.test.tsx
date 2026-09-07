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

const { approveMock, getMock, paymentCheckoutMock, paymentStatusMock, recordViewMock } = vi.hoisted(
  () => ({
    approveMock: vi.fn(),
    getMock: vi.fn(),
    paymentCheckoutMock: vi.fn(),
    paymentStatusMock: vi.fn(),
    recordViewMock: vi.fn(),
  }),
);

vi.mock("@/lib/api/public-proposals", () => ({
  publicProposalsApi: {
    get: getMock,
    recordView: recordViewMock,
    approve: approveMock,
    decline: vi.fn(),
    depositCheckout: vi.fn(),
    depositStatus: vi.fn(),
    paymentCheckout: paymentCheckoutMock,
    paymentStatus: paymentStatusMock,
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
    proposal_payment_paid: false,
    proposal_payment_required: false,
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
  paymentCheckoutMock.mockRejectedValue(new Error("checkout unavailable"));
  paymentStatusMock.mockResolvedValue({
    payment_paid: false,
    payment_required: true,
    payment_amount: 2600,
    completion_balance: 2600,
    currency: "USD",
    payment_choice: "fifty_percent_down",
  });
  approveMock.mockResolvedValue({
    token: "tok-abc",
    status: "approved",
    message: "Thank you",
    proposal_payment_required: false,
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
      name: "Yes, approve this proposal",
    });

    approve.focus();
    await user.keyboard("{Enter}");

    await waitFor(() => expect(approveMock).toHaveBeenCalledWith("tok-abc", 1, null));
  });

  it("sends the selected Permanent payment enum with no client-owned terms", async () => {
    const user = userEvent.setup();
    getMock.mockResolvedValue({
      ...proposal(),
      title: "Permanent Lighting",
      total: 5200,
      payment_options: {
        fifty_percent_down_amount: 2600,
        completion_balance: 2600,
        pay_in_full_amount: 5200,
      },
      proposal_document: {
        service: "permanent",
        category_sections: [
          {
            key: "permanent",
            label: "Permanent Lighting",
            min_applied: false,
            financed_total: 5200,
            cash_total: 5200,
            cash_savings: 0,
            monthly_payment: 216.67,
          },
        ],
      },
      financing: {
        provider: "GreenSky",
        plan_number: "6124",
        terms: [24],
        default_term: 24,
        apr: 0,
        monthly_payment: 417,
        monthly_by_term: { "24": 417 },
        disclaimer: "Estimated payment only. Subject to credit approval.",
      },
    });
    approveMock.mockResolvedValueOnce({
      token: "tok-abc",
      status: "approved",
      message: "Thank you",
      proposal_payment_choice: "fifty_percent_down",
      proposal_payment_required: true,
      proposal_payment_amount: 2600,
      deposit_required: false,
    });
    await renderPage();

    const down = await screen.findByRole("radio", { name: /50% down, \$2,600/i });
    await user.click(down);
    await user.click(screen.getByRole("button", { name: /accept & pay \$2,600/i }));

    await waitFor(() =>
      expect(approveMock).toHaveBeenCalledWith("tok-abc", 1, null, "fifty_percent_down"),
    );
    expect(approveMock.mock.calls[0]).toHaveLength(4);
    await waitFor(() => expect(paymentCheckoutMock).toHaveBeenCalledWith("tok-abc"));
  });

  it("restores the accepted amount when hosted checkout is cancelled", async () => {
    const user = userEvent.setup();
    getMock.mockResolvedValue({
      ...proposal(),
      status: "approved",
      is_decided: true,
      proposal_document: { service: "permanent" },
      payment_options: {
        fifty_percent_down_amount: 2600,
        completion_balance: 2600,
        pay_in_full_amount: 5200,
      },
      proposal_payment_choice: "fifty_percent_down",
      proposal_payment_amount: 2600,
      proposal_payment_paid: false,
      proposal_payment_required: true,
    });
    window.history.replaceState({}, "", "/p/quotes/tok-abc?payment=cancelled");

    await renderPage();
    expect(await screen.findByRole("heading", { name: /payment due · 50% down/i })).toBeVisible();
    expect(screen.getByText("$2,600.00")).toBeVisible();
    expect(screen.getByText(/\$2,600.00 remains due at completion/i)).toBeVisible();
    await user.click(screen.getByRole("button", { name: /continue to secure checkout/i }));
    await waitFor(() => expect(paymentCheckoutMock).toHaveBeenCalledWith("tok-abc"));
    expect(await screen.findByRole("alert")).toHaveTextContent(/could not open/i);
  });

  it("reconciles a delayed Stripe return into the paid state", async () => {
    const unpaid = {
      ...proposal(),
      status: "approved",
      is_decided: true,
      proposal_document: { service: "permanent" },
      payment_options: {
        fifty_percent_down_amount: 2600,
        completion_balance: 2600,
        pay_in_full_amount: 5200,
      },
      proposal_payment_choice: "fifty_percent_down",
      proposal_payment_amount: 2600,
      proposal_payment_paid: false,
      proposal_payment_required: true,
    };
    getMock.mockResolvedValueOnce(unpaid).mockResolvedValue({
      ...unpaid,
      proposal_payment_paid: true,
      proposal_payment_required: false,
    });
    paymentStatusMock.mockResolvedValueOnce({
      payment_paid: true,
      payment_required: false,
      payment_amount: 2600,
      completion_balance: 2600,
      currency: "USD",
      payment_choice: "fifty_percent_down",
    });
    window.history.replaceState({}, "", "/p/quotes/tok-abc?payment=paid");

    await renderPage();
    expect(await screen.findByRole("heading", { name: "Payment received" })).toBeVisible();
    expect(screen.getByText(/\$2,600.00 remains due at completion/i)).toBeVisible();
    expect(paymentStatusMock).toHaveBeenCalledWith("tok-abc");
  });
});
