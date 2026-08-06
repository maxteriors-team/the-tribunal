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

/**
 * A Christmas quote is a different sale, so it is a different page.
 *
 * The default proposal sells design, craftsmanship, and a workmanship warranty.
 * A homeowner buying seasonal lighting is deciding something else entirely: who
 * owns the lights, who fixes a dark bulb in December, and who takes it all down.
 * These tests pin the swap in both directions, because leaking either pitch onto
 * the other product tells the customer something untrue about what they bought.
 */
describe("ClientProposalView — seasonal Christmas", () => {
  const VALUE_PROPS = [
    {
      title: "A Worry-Free Christmas",
      body: "Maintenance is included through December 23.",
    },
    {
      title: "Every Light Is Ours",
      body: "We own the bulbs, strands, and clips.",
    },
  ];

  const christmasSection = (
    overrides: Record<string, unknown> = {},
  ): Record<string, unknown> => ({
    key: "christmas",
    label: "Christmas Lighting",
    lines: [{ label: "Roofline", line_total: 1800, quantity: 300 }],
    value_props: VALUE_PROPS,
    financed_total: 1800,
    cash_total: 1800,
    cash_savings: 0,
    monthly_payment: 0,
    min_applied: false,
    takedown: true,
    storage: false,
    ...overrides,
  });

  function christmasDoc(overrides: Record<string, unknown> = {}) {
    return {
      version: 1,
      service: "christmas",
      client: { first_name: "Dana", last_name: "Homeowner" },
      tier_order: [],
      tiers: [],
      additional_charges: [],
      category_sections: [christmasSection()],
      grand_financed_total: 1800,
      mockups: [],
      ...overrides,
    };
  }

  function renderChristmas(doc: Record<string, unknown> = christmasDoc()) {
    const data = proposal({
      packages: [],
      total: 1800,
      subtotal: 1800,
      deposit_required: false,
      deposit_amount: 0,
      deposit_percentage: 0,
      proposal_document: doc as unknown as Record<string, unknown>,
    });
    render(
      <ClientProposalView
        data={data}
        document={parseProposalDocument(data.proposal_document)!}
        justApproved={false}
        justDeclined={false}
        busy={false}
        actionError={false}
        onApprove={vi.fn()}
        onDecline={vi.fn()}
      />,
      { wrapper },
    );
  }

  const root = () => document.querySelector(".proposal-view");

  it("dresses the page for Christmas and sells the season, not a build", () => {
    renderChristmas();

    expect(root()).toHaveClass("is-christmas");
    // The section owns the pitch; each promise is a heading beneath it, so a
    // screen reader can jump the list instead of hearing one wall of text.
    expect(
      screen.getByRole("heading", { level: 2, name: /worry-free christmas/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 3, name: /worry-free christmas/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/maintenance is included through december 23/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/we own the bulbs/i)).toBeInTheDocument();
    // Seasonal-only structure the homeowner is actually buying.
    expect(screen.getByText(/we take it down/i)).toBeInTheDocument();
    expect(screen.getByText(/off-season storage/i)).toBeInTheDocument();
    // The permanent-install pitch must not survive the swap: a seasonal job has
    // no workmanship warranty and is not "designed around how you live in it".
    expect(screen.queryByText(/1-year workmanship warranty/i)).toBeNull();
    expect(screen.queryByText(/a designer, not a salesperson/i)).toBeNull();
  });

  it("never quotes a monthly payment on a seasonal job", () => {
    // Christmas is sold as one up-front seasonal price — the proposal says so in
    // as many words ("Affordable, Up-Front Pricing"). A financing estimate
    // beside that copy contradicts it, and the snapshot still carries a
    // financing block from the workspace config, so this must be suppressed at
    // render rather than assumed absent.
    renderChristmas(
      christmasDoc({
        financing: {
          enabled: true,
          provider: "Wisetack",
          terms: [24],
          default_term: 24,
          max_amount: 25000,
          headline: "A monthly payment may fit your project.",
          body: null,
          points: [],
          disclaimer: "Estimates only.",
        },
        grand_monthly_payment: 156,
      }),
    );

    expect(document.querySelector(".financing-estimate")).toBeNull();
    expect(screen.queryByText(/\/month/i)).toBeNull();
    expect(screen.queryByText(/wisetack/i)).toBeNull();
    expect(screen.queryByText(/monthly payment/i)).toBeNull();
    // The one-time price it was actually sold at still shows.
    expect(screen.getAllByText("$1,800").length).toBeGreaterThan(0);
  });

  it("leaves a landscape proposal completely undressed", () => {
    renderView();

    expect(root()).not.toHaveClass("is-christmas");
    expect(screen.queryByText(/worry-free christmas/i)).toBeNull();
    expect(screen.getByText(/a designer, not a salesperson/i)).toBeInTheDocument();
  });

  it("stays neutral on a mixed quote, which is not only Christmas", () => {
    renderChristmas(
      christmasDoc({
        service: "mixed",
        category_sections: [
          christmasSection(),
          { ...christmasSection(), key: "permanent", label: "Permanent" },
        ],
      }),
    );

    expect(root()).not.toHaveClass("is-christmas");
  });

  it("renders nothing for a snapshot saved before value props existed", () => {
    // Legacy snapshots have no `service` and no `value_props`. The page must
    // still present as Christmas (the section key proves it) and must simply
    // omit the promises rather than render an empty block.
    renderChristmas(
      christmasDoc({
        service: undefined,
        category_sections: [christmasSection({ value_props: undefined })],
      }),
    );

    expect(root()).toHaveClass("is-christmas");
    expect(document.querySelector(".xv-section")).toBeNull();
    expect(screen.queryByText(/maintenance is included/i)).toBeNull();
    // The price it was sold at still renders.
    expect(screen.getByText("Christmas Lighting")).toBeInTheDocument();
  });
});
