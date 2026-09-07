import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
      terms: [24],
      default_term: 24,
      apr: 0,
      monthly_payment: 417,
      monthly_by_term: { "24": 417 },
      headline: null,
      body: null,
      points: [],
      disclaimer: "Estimated payment only. Subject to credit approval.",
    },
    proposal_payment_paid: false,
    proposal_payment_required: false,
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
  const onApprove = vi.fn();
  const onDecline = vi.fn();
  render(
    <PlainQuoteView
      data={proposal(overrides)}
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

describe("plain quote financing", () => {
  it("keeps financing display-only beside two exact payment choices", () => {
    renderQuote({
      title: "Permanent Lighting",
      proposal_document: { service: "permanent" },
      payment_options: {
        fifty_percent_down_amount: 4500,
        completion_balance: 4500,
        pay_in_full_amount: 9000,
      },
    });

    expect(screen.getByText("$417/mo")).toBeVisible();
    expect(screen.getByText("for 24 months")).toBeVisible();
    expect(screen.queryByRole("radio", { name: /financing/i })).toBeNull();
    const options = screen.getByRole("radiogroup", { name: /payment options/i });
    expect(within(options).getAllByRole("radio")).toHaveLength(2);
    expect(options).not.toHaveTextContent(/GreenSky|plan 6124|subject to credit approval/i);
    expect(screen.getByText("Estimated payment only. Subject to credit approval.")).toBeVisible();
    expect(screen.getByRole("link", { name: "Terms and Conditions" })).toHaveAttribute(
      "href",
      "https://maxteriorslighting.com/terms-and-conditions/",
    );
  });

  it("shows 50% down and pay-in-full as the only approval schedules", async () => {
    const user = userEvent.setup();
    renderQuote({
      subtotal: 8475,
      total: 8475,
      deposit_percentage: 50,
      deposit_amount: 4237.5,
      deposit_required: true,
      proposal_document: { service: "permanent" },
      payment_options: {
        fifty_percent_down_amount: 4237.5,
        completion_balance: 4237.5,
        pay_in_full_amount: 8475,
      },
      financing: {
        provider: "GreenSky",
        terms: [24],
        default_term: 24,
        apr: 0,
        monthly_payment: 417,
        monthly_by_term: { "24": 417 },
        disclaimer: "Estimated payment only. Subject to credit approval.",
      },
    });

    expect(screen.getByText("$417/mo")).toBeVisible();
    expect(screen.getByText("for 24 months")).toBeVisible();
    expect(screen.getByText("Balance due at completion")).toBeVisible();
    expect(screen.queryByText("$4,237.50 at completion")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /pay deposit/i })).toBeNull();
    const down = screen.getByRole("radio", { name: /50% down, \$4,237.50/i });
    await user.click(down);
    const approve = screen.getByRole("button", { name: /approve and pay \$4,237.50/i });
    expect(approve).toBeVisible();
    expect(approve).toHaveTextContent("Approve and pay");
  });

  it("shows the branded mockup, only three prices, and explicit decisions", async () => {
    const user = userEvent.setup();
    const actions = renderQuote({
      title: "Permanent lighting proposal",
      price_range: { low: 9000, high: 11800 },
      payment_options: {
        fifty_percent_down_amount: 4500,
        completion_balance: 4500,
        pay_in_full_amount: 9000,
      },
      branding: {
        business_name: "Maxteriors",
        brand_color: "#304854",
        accent_color: "#fcb400",
        logo_url: "https://api.example.com/static/brand/maxteriors-logo.png",
      },
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

    expect(screen.getByRole("img", { name: "Maxteriors" })).toBeVisible();
    expect(
      screen.getByRole("img", {
        name: "Pat permanent roofline proposed permanent lighting",
      }),
    ).toHaveAttribute("src", "data:image/jpeg;base64,/9j/2Q==");
    expect(screen.getByRole("heading", { name: "Project scope" })).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Estimated project range" })).toBeNull();
    expect(document.querySelector(".pq-range")).toBeNull();
    expect(document.querySelector(".pq-amount")).toBeNull();
    expect(document.querySelector(".pq-totals")).toBeNull();
    expect(document.querySelector(".pq-table")).not.toHaveTextContent("$");
    expect(
      Array.from(document.querySelectorAll(".payment-option__price"), (node) => node.textContent),
    ).toEqual(["$417/mo", "$4,500", "$9,000"]);

    await user.click(screen.getByRole("radio", { name: /pay in full, \$9,000/i }));
    await user.click(screen.getByRole("button", { name: /approve and pay \$9,000/i }));
    expect(actions.onApprove).toHaveBeenCalledWith("pay_in_full");

    await user.click(screen.getByRole("button", { name: "No, decline" }));
    await user.type(screen.getByRole("textbox"), "Timing changed");
    await user.click(screen.getByRole("button", { name: "Confirm decline" }));
    expect(actions.onDecline).toHaveBeenCalledWith("Timing changed");
    expect(screen.getByRole("link", { name: "Terms and Conditions" })).toBeVisible();
  });

  it("keeps detailed prices for a non-Permanent proposal", () => {
    renderQuote({
      title: "Roof replacement",
      proposal_document: { service: "landscape" },
      price_range: { low: 350, high: 400 },
      total: 400,
      subtotal: 400,
    });

    expect(screen.queryByRole("radiogroup", { name: "PAYMENT OPTIONS" })).not.toBeInTheDocument();
    expect(screen.queryByText(/financing/i)).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Estimated project range" })).toBeVisible();
    expect(document.querySelector(".pq-amount")).not.toBeNull();
    expect(document.querySelector(".pq-totals")).not.toBeNull();
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
    expect(screen.getByRole("button", { name: "Approve & Pay Now" })).toBeVisible();
  });

  it("hides approval actions after the proposal expires", () => {
    renderQuote({ is_expired: true });

    expect(screen.queryByRole("button", { name: /approve/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /decline/i })).not.toBeInTheDocument();
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
