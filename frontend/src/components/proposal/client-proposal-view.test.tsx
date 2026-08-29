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
import { cleanup, render, screen, within } from "@testing-library/react";
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
    token: "proposal-token",
    number: "Q-1001",
    status: "sent",
    proposal_version: 1,
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

describe("customer-facing tenant branding", () => {
  it("renders a second workspace without leaking the first tenant's brand", () => {
    renderView({
      branding: {
        business_name: "Northstar Outdoor Lighting",
        brand_color: "#123456",
        accent_color: "#654321",
      },
    });

    expect(screen.getAllByText("Northstar Outdoor Lighting")).not.toHaveLength(0);
    expect(screen.queryByText(/maxteriors/i)).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Terms and Conditions" })).toHaveAttribute(
      "href",
      "https://maxteriorslighting.com/terms-and-conditions/",
    );
  });
});

describe("ClientProposalView — visual checkout", () => {
  it("shows the saved mockup, server price, deposit, and connected acceptance action", async () => {
    const onApprove = renderView({
      packages: [],
      proposal_document: {
        ...DOCUMENT,
        mockups: [
          {
            image: "data:image/png;base64,AAAA",
            caption: "Front elevation lighting design",
          },
        ],
      } as unknown as Record<string, unknown>,
    }).onApprove;

    expect(screen.getByRole("img", { name: "Front elevation lighting design" })).toBeVisible();
    const visualCheckout = screen.getByRole("region", { name: "Your lighting proposal" });
    expect(within(visualCheckout).getByText("$16,782")).toBeVisible();
    expect(
      within(visualCheckout).getByText(
        /\$8,391 due today; the remaining balance follows your proposal terms/i,
      ),
    ).toBeVisible();
    await userEvent.click(
      within(visualCheckout).getByRole("button", { name: "Accept & Pay $8,391" }),
    );
    expect(onApprove).toHaveBeenCalledWith("best");
    expect(
      within(visualCheckout).getByText(
        /acceptance is recorded before the existing secure payment checkout opens/i,
      ),
    ).toBeVisible();
  });
});

describe("ClientProposalView — measured Bistro pricing", () => {
  it("names temporary and permanent runs without legacy Classic or Color labels", () => {
    const bistroDocument = {
      ...DOCUMENT,
      bistro: {
        pricing_mode: "installation",
        feet: 150,
        product: "installation",
        tier: "",
        per_ft: 0,
        hardware: 0,
        minimum: 500,
        lights_cost: 2248,
        poles_cost: 786,
        raw_total: 3034,
        total: 3034,
        min_applied: false,
        ordered_ft: 150,
        installations: [
          {
            installation: "temporary",
            label: "Temporary Bistro Lighting",
            feet: 100,
            pole_count: 3,
            lights_per_ft: 10,
            poles_each: 400,
            lights_cost: 1124,
            poles_cost: 449,
            total: 1573,
          },
          {
            installation: "permanent",
            label: "Permanent Bistro Lighting",
            feet: 50,
            pole_count: 2,
            lights_per_ft: 20,
            poles_each: 350,
            lights_cost: 1124,
            poles_cost: 337,
            total: 1461,
          },
        ],
        lines: [],
      },
    };

    renderView({
      proposal_document: bistroDocument as unknown as Record<string, unknown>,
    });

    expect(screen.getAllByText(/Temporary \+ Permanent/)).toHaveLength(2);
    // Two runs, so each is named to tell them apart, and each carries its own
    // price -- but never the footage we measured.
    expect(screen.getByText(/Temporary: String lights — \$1,124/i)).toBeVisible();
    expect(screen.getByText(/Temporary: 3 support poles — \$449/i)).toBeVisible();
    expect(screen.getByText(/Permanent: String lights — \$1,124/i)).toBeVisible();
    expect(screen.getByText(/Permanent: 2 support poles — \$337/i)).toBeVisible();
    expect(screen.queryByText(/Classic Bistro|Color Changing Bistro/i)).not.toBeInTheDocument();
    // The whole patio section is feet-free: no bullet, no headline, no subtitle.
    expect(screen.queryByText(/\d\s*(ft|feet|linear)/i)).not.toBeInTheDocument();
  });

  it("lets the customer accept a Bistro-only estimate without fake package choices", async () => {
    const bistroOnlyDocument = {
      ...DOCUMENT,
      tiers: [tier("best", "Best", "Best", 0), tier("good", "Good", "Good", 0)],
      bistro: {
        pricing_mode: "installation",
        feet: 312.5,
        product: "installation",
        tier: "",
        per_ft: 0,
        hardware: 0,
        minimum: 0,
        lights_cost: 7022,
        poles_cost: 787,
        raw_total: 7809,
        total: 7809,
        min_applied: false,
        ordered_ft: 312.5,
        installations: [
          {
            installation: "permanent",
            label: "Permanent Bistro Lighting",
            feet: 312.5,
            pole_count: 2,
            lights_per_ft: 20,
            poles_each: 350,
            lights_cost: 7022,
            poles_cost: 787,
            total: 7809,
          },
        ],
        lines: [],
      },
    };
    const { onApprove } = renderView({
      total: 7809,
      deposit_amount: 0,
      deposit_required: false,
      packages: PACKAGES.map((offer) => ({ ...offer, total: 7809, deposit_amount: 0 })),
      proposal_document: bistroOnlyDocument as unknown as Record<string, unknown>,
    });

    expect(
      screen.queryByRole("radiogroup", { name: /choose your package/i }),
    ).not.toBeInTheDocument();
    const approve = acceptButton();
    await userEvent.click(approve);
    expect(onApprove).toHaveBeenCalledWith("best");
  });
});

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
        disclaimer: "Payment estimates are not offers and are subject to credit approval.",
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
    expect(card(/The Premier/)).toHaveTextContent("Estimated payment options below");

    await user.click(within(estimate).getByRole("button", { name: /12 months.*\$1,398\/mo est/i }));
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

  it("keeps selected-package terms, acceptance, and deposit without a chooser", async () => {
    const user = userEvent.setup();
    const lockedDocument = {
      ...DOCUMENT,
      tier_order: ["best"],
      tiers: [DOCUMENT.tiers[0]],
    };
    const { onApprove } = renderView({
      packages: [],
      proposal_document: lockedDocument as unknown as Record<string, unknown>,
    });

    expect(screen.queryByRole("radiogroup")).not.toBeInTheDocument();
    expect(screen.getByText(/your selected package/i)).toBeInTheDocument();
    expect(screen.getByText("The Premier")).toBeVisible();
    expect(screen.queryByText("The Starter")).not.toBeInTheDocument();
    expect(screen.getByText("$8,391.00")).toBeVisible();
    expect(screen.getByRole("link", { name: "Terms and Conditions" })).toBeVisible();
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

  const christmasSection = (overrides: Record<string, unknown> = {}): Record<string, unknown> => ({
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
    expect(screen.getByText(/maintenance is included through december 23/i)).toBeInTheDocument();
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

  it("shows every designed photo, and still shows the one on older snapshots", () => {
    // A rep designs several angles of the same house (front, back, walkway) and
    // the client sees all of them. Snapshots saved before a design could span
    // photos carry a single `image` — that one must still render.
    renderView({
      proposal_document: {
        ...DOCUMENT,
        night_preview: {
          image: "data:image/jpeg;base64,FRONT",
          images: ["data:image/jpeg;base64,FRONT", "data:image/jpeg;base64,BACK"],
        },
      } as unknown as Record<string, unknown>,
    });

    const frames = document.querySelectorAll(".pnight-frame img");
    expect(frames).toHaveLength(2);
    expect(frames[0]).toHaveAttribute("src", "data:image/jpeg;base64,FRONT");
    expect(frames[1]).toHaveAttribute("src", "data:image/jpeg;base64,BACK");
    expect(screen.getByText(/design preview \(2 of 2\)/i)).toBeInTheDocument();

    cleanup();
    renderView({
      proposal_document: {
        ...DOCUMENT,
        night_preview: { image: "data:image/jpeg;base64,LEGACY" },
      } as unknown as Record<string, unknown>,
    });

    const legacy = document.querySelectorAll(".pnight-frame img");
    expect(legacy).toHaveLength(1);
    expect(legacy[0]).toHaveAttribute("src", "data:image/jpeg;base64,LEGACY");
    // A lone photo isn't numbered — "1 of 1" is noise on a client page.
    expect(screen.queryByText(/design preview \(/i)).toBeNull();
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

describe("operator-authored project terms", () => {
  const NARRATIVE = {
    design_intent: "Warm arrival lighting with focal uplights on the oaks.",
    electrical_responsibility: "Client supplies the 120V GFCI outlet.",
    commitments: "Five-year workmanship warranty on all fixtures.",
    signature_name: "Raymond Fair",
    signature_date: "2026-08-28",
  };

  /** Render the client page with a narrative on the stored snapshot. */
  const withNarrative = (narrative: Partial<typeof NARRATIVE> | null) =>
    renderView({
      proposal_document: { ...DOCUMENT, narrative } as unknown as Record<string, unknown>,
    });

  it("renders every persisted narrative field the rep filled in", () => {
    // These four inputs were bound to nothing in the quote builder: a rep could
    // type them, save, and have them silently discarded before reaching here.
    withNarrative(NARRATIVE);

    expect(screen.getByText("Design intent")).toBeVisible();
    expect(screen.getByText(NARRATIVE.design_intent)).toBeVisible();
    expect(screen.getByText("Electrical responsibility")).toBeVisible();
    expect(screen.getByText(NARRATIVE.electrical_responsibility)).toBeVisible();
    expect(screen.getByText("Our commitments")).toBeVisible();
    expect(screen.getByText(NARRATIVE.commitments)).toBeVisible();
  });

  it("labels a recorded signatory as prepared-for, never as signed", () => {
    // The name is something the rep typed, not consent the client gave. The
    // binding acceptance is the approve action, which the server timestamps.
    withNarrative(NARRATIVE);

    expect(screen.getByText("Prepared for signature")).toBeVisible();
    expect(screen.getByText(/Raymond Fair · 2026-08-28/)).toBeVisible();
    expect(screen.queryByText(/signed by/i)).toBeNull();
  });

  it("omits each section the rep left blank instead of rendering an empty heading", () => {
    withNarrative({ design_intent: NARRATIVE.design_intent });

    expect(screen.getByText("Design intent")).toBeVisible();
    expect(screen.queryByText("Electrical responsibility")).toBeNull();
    expect(screen.queryByText("Our commitments")).toBeNull();
    expect(screen.queryByText("Prepared for signature")).toBeNull();
  });

  it("renders no narrative sections at all for a snapshot without one", () => {
    withNarrative(null);

    expect(screen.queryByText("Design intent")).toBeNull();
    expect(screen.queryByText("Our commitments")).toBeNull();
    expect(screen.queryByText("Prepared for signature")).toBeNull();
  });
});
