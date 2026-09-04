import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import type { PublicProposal } from "@/types/proposal";

import { PlainQuoteView } from "./plain-quote-view";

function proposal(overrides: Partial<PublicProposal> = {}): PublicProposal {
  return {
    token: "public-token",
    number: "QUO-1001",
    title: "Roof replacement",
    status: "sent",
    proposal_version: 1,
    currency: "USD",
    subtotal: 9000,
    tax_amount: 0,
    discount_amount: 0,
    total: 9000,
    financing: {
      provider: "GreenSky",
      plan_number: "6124",
      terms: [24],
      default_term: 24,
      apr: 0,
      monthly_payment: 375,
      monthly_by_term: { "24": 375 },
      headline: null,
      body: null,
      points: [],
      disclaimer: "Estimated payment only. Subject to credit approval.",
    },
    is_expired: false,
    is_decided: false,
    deposit_paid: false,
    line_items: [
      {
        name: "Roof replacement",
        quantity: 1,
        unit_price: 9000,
        discount: 0,
        total: 9000,
      },
    ],
    branding: {
      business_name: "Maxteriors",
      brand_color: "#d4af5a",
      accent_color: "#d4af5a",
    },
    ...overrides,
  };
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function renderQuote(overrides: Partial<PublicProposal> = {}) {
  render(
    <PlainQuoteView
      data={proposal(overrides)}
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

describe("plain quote financing", () => {
  it("shows equal Permanent Lighting payment options from the server estimate", () => {
    renderQuote({
      title: "Permanent Lighting",
      proposal_document: { service: "permanent" },
    });

    expect(screen.getAllByText("$9,000").length).toBeGreaterThanOrEqual(2);
    const options = screen.getByRole("radiogroup", { name: "PAYMENT OPTIONS" });
    expect(options).toHaveTextContent("Approximately $375/month for 24 months");
    expect(options).toHaveTextContent("GreenSky plan 6124");
    expect(options).toHaveTextContent("Subject to credit approval");
    expect(screen.getByRole("link", { name: "Terms and Conditions" })).toHaveAttribute(
      "href",
      "https://maxteriorslighting.com/terms-and-conditions/",
    );
  });

  it("shows the saved permanent-lighting preview before acceptance", () => {
    renderQuote({
      title: "Permanent lighting proposal",
      proposal_document: {
        service: "permanent",
        mockups: [
          {
            image: "data:image/jpeg;base64,/9j/2Q==",
            caption: "Pat permanent roofline proposed permanent lighting",
          },
        ],
      },
    });

    expect(screen.getByRole("heading", { name: "Preview your permanent lighting" })).toBeVisible();
    expect(
      screen.getByRole("img", {
        name: "Pat permanent roofline proposed permanent lighting",
      }),
    ).toHaveAttribute("src", "data:image/jpeg;base64,/9j/2Q==");
    expect(screen.getByRole("button", { name: /^✓\s+Approve Proposal$/ })).toBeVisible();
    expect(screen.getByRole("link", { name: "Terms and Conditions" })).toBeVisible();
  });

  it("shows no financing language for a non-Permanent proposal", () => {
    renderQuote({
      title: "Roof replacement",
      proposal_document: { service: "landscape" },
      total: 400,
      subtotal: 400,
    });

    expect(screen.queryByRole("radiogroup", { name: "PAYMENT OPTIONS" })).not.toBeInTheDocument();
    expect(screen.queryByText(/financing/i)).not.toBeInTheDocument();
  });
});

describe("plain quote on-site payment", () => {
  it("labels a 100% deposit as full payment", () => {
    renderQuote({
      deposit_percentage: 100,
      deposit_amount: 9000,
      deposit_required: true,
    });

    expect(screen.getByText("Payment Due Today")).toBeVisible();
    expect(screen.getByText("Full one-time total")).toBeVisible();
    expect(screen.getByRole("button", { name: "Pay Now" })).toBeVisible();
    expect(screen.getByRole("button", { name: /Approve & Pay Now/ })).toBeVisible();
  });
});

describe("plain quote branding", () => {
  it("renders the workspace logo, since this page is the receipt of record", () => {
    renderQuote({
      branding: {
        business_name: "Maxteriors",
        brand_color: "#d4af5a",
        accent_color: "#d4af5a",
        logo_url: "https://api.example.com/static/brand/maxteriors-logo.png",
      },
    });

    expect(screen.getByRole("img", { name: "Maxteriors" })).toHaveAttribute(
      "src",
      "https://api.example.com/static/brand/maxteriors-logo.png",
    );
  });

  it("renders no logo image when the workspace has not set one", () => {
    renderQuote();

    expect(screen.queryByRole("img", { name: "Maxteriors" })).toBeNull();
  });
});
