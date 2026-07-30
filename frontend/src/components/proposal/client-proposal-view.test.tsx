/**
 * The client picks their package, then pays for that package.
 *
 * The public proposal page is where a homeowner spends money, so the contract
 * these tests pin down is narrow and load-bearing: the card they choose is the
 * package the accept button names, the amount it quotes is the one the server
 * priced for that package, and the key that reaches `onApprove` is the one they
 * chose. Nothing here computes money — the page renders server figures.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import type { PublicProposal, PublicProposalPackage } from "@/types/proposal";

import { ClientProposalView } from "./client-proposal-view";
import { parseProposalDocument } from "./document";

function tier(key: string, label: string, name: string, base: number) {
  return {
    key,
    label,
    name,
    experience: `${name} experience`,
    warranty: null,
    marker: null,
    value_tag: null,
    popular: false,
    points: [`${name} point`],
    lines: [],
    pricing: {
      base,
      additional: 0,
      financed_total: base,
      cash_total: base,
      cash_savings: 0,
      monthly_payment: 0,
      monthly_by_term: {},
      commission_financed: 0,
      commission_cash: 0,
    },
  };
}

const DOCUMENT = {
  version: 1,
  client: { first_name: "Dana", last_name: "Homeowner" },
  tier_order: ["best", "good"],
  tiers: [
    tier("best", "Best — The Premier", "The Premier", 16782),
    tier("good", "Good — The Starter", "The Starter", 9400),
  ],
  selected_tier: "best",
  headline_tier: "best",
  additional_charges: [],
  category_sections: [],
  mockups: [],
};

const PACKAGES: PublicProposalPackage[] = [
  {
    key: "best",
    label: "Best — The Premier",
    name: "The Premier",
    total: 16782,
    deposit_amount: 8391,
    is_selected: true,
  },
  {
    key: "good",
    label: "Good — The Starter",
    name: "The Starter",
    total: 9400,
    deposit_amount: 4700,
    is_selected: false,
  },
];

function proposal(overrides: Partial<PublicProposal> = {}): PublicProposal {
  return {
    token: "tok-1",
    number: "Q-1001",
    status: "sent",
    currency: "USD",
    subtotal: 16782,
    tax_amount: 0,
    discount_amount: 0,
    total: 16782,
    is_expired: false,
    is_decided: false,
    deposit_percentage: 50,
    deposit_amount: 8391,
    deposit_paid: false,
    deposit_required: true,
    packages: PACKAGES,
    line_items: [],
    branding: {
      business_name: "Maxteriors Lighting",
      brand_color: "#d4af5a",
      accent_color: "#d4af5a",
    },
    proposal_document: DOCUMENT as unknown as Record<string, unknown>,
    ...overrides,
  };
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function renderView(overrides: Partial<PublicProposal> = {}) {
  const data = proposal(overrides);
  const onApprove = vi.fn();
  const onDecline = vi.fn();
  render(
    <ClientProposalView
      data={data}
      document={parseProposalDocument(data.proposal_document)!}
      justApproved={false}
      justDeclined={false}
      busy={false}
      actionError={false}
      onApprove={onApprove}
      onDecline={onDecline}
    />,
    { wrapper },
  );
  return { onApprove, onDecline };
}

const card = (name: RegExp) => screen.getByRole("radio", { name });

/** The closing CTA, as distinct from the deposit panel's own pay button. */
const acceptButton = () => {
  const cta = document.querySelector<HTMLElement>(".cta-buttons");
  if (!cta) throw new Error("No CTA section rendered");
  return within(cta).getByRole("button", { name: /accept|approve proposal/i });
};

describe("client package selection", () => {
  it("offers each package as a choice, starting on the rep's recommendation", () => {
    renderView();

    const group = screen.getByRole("radiogroup", { name: /choose your package/i });
    const options = within(group).getAllByRole("radio");
    expect(options).toHaveLength(2);
    expect(card(/The Premier/)).toBeChecked();
    expect(card(/The Starter/)).not.toBeChecked();
  });

  it("prices each package with its own total and money due today", () => {
    renderView();

    expect(card(/The Premier/)).toHaveTextContent("$16,782");
    expect(card(/The Premier/)).toHaveTextContent("$8,391 due today to start");
    expect(card(/The Starter/)).toHaveTextContent("$9,400");
    expect(card(/The Starter/)).toHaveTextContent("$4,700 due today to start");
  });

  it("names the chosen package and its deposit on the accept button", async () => {
    const user = userEvent.setup();
    renderView();

    expect(acceptButton()).toHaveTextContent("Accept The Premier & Pay $8,391");

    await user.click(card(/The Starter/));
    expect(card(/The Starter/)).toBeChecked();
    expect(card(/The Premier/)).not.toBeChecked();
    expect(acceptButton()).toHaveTextContent("Accept The Starter & Pay $4,700");
  });

  it("sends the chosen package key to approve", async () => {
    const user = userEvent.setup();
    const { onApprove } = renderView();

    await user.click(card(/The Starter/));
    await user.click(acceptButton());

    expect(onApprove).toHaveBeenCalledWith("good");
  });

  it("accepts the rep's package when the client changes nothing", async () => {
    const user = userEvent.setup();
    const { onApprove } = renderView();

    await user.click(acceptButton());
    expect(onApprove).toHaveBeenCalledWith("best");
  });

  it("is keyboard-operable as a radiogroup", async () => {
    const user = userEvent.setup();
    const { onApprove } = renderView();

    await user.tab();
    card(/The Premier/).focus();
    await user.keyboard("{ArrowRight}");
    expect(card(/The Starter/)).toBeChecked();

    await user.click(acceptButton());
    expect(onApprove).toHaveBeenCalledWith("good");
  });

  it("quotes the chosen package in the deposit panel too", async () => {
    const user = userEvent.setup();
    renderView();

    const pay = screen.getByRole("button", { name: /accept & pay deposit/i });
    expect(pay).toBeInTheDocument();
    // The panel's headline amount tracks the selection, not the rep's pick.
    await user.click(card(/The Starter/));
    expect(screen.getByText("$4,700.00")).toBeInTheDocument();
  });

  it("renders configured payment estimates with their disclaimer", async () => {
    const user = userEvent.setup();
    const financed = {
      ...DOCUMENT,
      grand_monthly_payment: 699,
      selected_monthly_payment: 699,
      financing: {
        enabled: true,
        provider: "Wisetack",
        terms: [12, 24],
        default_term: 24,
        max_amount: 25000,
        headline: "0% APR financing available.",
        body: "Pay monthly instead.",
        points: ["No interest, ever"],
        disclaimer:
          "Payment estimates are not offers and are subject to credit approval.",
      },
      tiers: DOCUMENT.tiers.map((t) => ({
        ...t,
        pricing: {
          ...t.pricing,
          monthly_payment: 699,
          monthly_by_term: { "12": 1398, "24": 699 },
        },
      })),
    };
    renderView({
      proposal_document: financed as unknown as Record<string, unknown>,
    });

    const estimate = screen.getByRole("complementary", {
      name: /estimated financing payments/i,
    });
    expect(estimate).toHaveTextContent("$699/month");
    expect(estimate).toHaveTextContent(
      "Payment estimates are not offers and are subject to credit approval.",
    );
    expect(estimate).toHaveTextContent("Wisetack");
    expect(card(/The Premier/)).toHaveTextContent(
      "Estimated payment options below",
    );

    await user.click(
      within(estimate).getByRole("button", { name: /12 months.*\$1,398\/mo est/i }),
    );
    expect(estimate).toHaveTextContent("$1,398/month");
    // Financing presentation is additive; package pricing remains untouched.
    expect(card(/The Premier/)).toHaveTextContent("$16,782");
  });

  it("stops offering a choice once the proposal is decided", () => {
    renderView({ status: "approved", is_decided: true });

    expect(screen.queryByRole("radiogroup")).not.toBeInTheDocument();
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
    expect(screen.getByText(/thank you, dana/i)).toBeInTheDocument();
  });

  it("presents a single-package proposal as a plain recommendation", async () => {
    const user = userEvent.setup();
    const { onApprove } = renderView({ packages: [] });

    expect(screen.queryByRole("radiogroup")).not.toBeInTheDocument();
    expect(screen.getByText(/your selected package/i)).toBeInTheDocument();
    // Falls back to the quote-level deposit rather than a package's.
    expect(acceptButton()).toHaveTextContent("Pay $8,391");

    await user.click(acceptButton());
    expect(onApprove).toHaveBeenCalledWith("best");
  });
});
