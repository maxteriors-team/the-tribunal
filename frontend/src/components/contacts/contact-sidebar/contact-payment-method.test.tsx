import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { server } from "@/test/msw/server";

import { ContactPaymentMethods } from "./contact-payment-method";

const ORIGIN = "http://localhost:3000";
const WORKSPACE_ID = "ws_1";
const CONTACT_ID = 7;
const BASE = `${ORIGIN}/api/v1/workspaces/${WORKSPACE_ID}/contacts/${CONTACT_ID}/payment-methods`;

const { toastSuccess, toastError } = vi.hoisted(() => ({
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: { success: toastSuccess, error: toastError, warning: vi.fn() },
}));

afterEach(() => {
  toastSuccess.mockReset();
  toastError.mockReset();
});

function savedCard(overrides: Record<string, unknown> = {}) {
  return {
    id: "pm-row-1",
    contact_id: CONTACT_ID,
    brand: "visa",
    last4: "4242",
    exp_month: 12,
    exp_year: 2032,
    is_default: true,
    status: "active",
    mandate_text_version: "2026-08-05.v1",
    mandate_accepted_at: "2026-08-05T12:00:00Z",
    created_at: "2026-08-05T12:00:00Z",
    ...overrides,
  };
}

function renderSection() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return render(
    <ContactPaymentMethods workspaceId={WORKSPACE_ID} contactId={CONTACT_ID} />,
    { wrapper }
  );
}

describe("contact payment methods", () => {
  it("shows the saved card without ever showing a card number", async () => {
    server.use(http.get(BASE, () => HttpResponse.json([savedCard()])));
    renderSection();

    expect(await screen.findByText(/Visa .* 4242/)).toBeInTheDocument();
    expect(screen.getByText("Expires 12/2032")).toBeInTheDocument();

    // Structural: nothing rendered may contain a PAN-shaped digit run.
    expect(document.body.textContent ?? "").not.toMatch(/\d{13,19}/);
  });

  it("tells the operator how to get a card when there is none", async () => {
    server.use(http.get(BASE, () => HttpResponse.json([])));
    renderSection();

    expect(
      await screen.findByText(/No card on file\. Send a link/i)
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /send card-on-file link/i })
    ).toBeInTheDocument();
  });

  it("copies a freshly minted setup link and says when it expires", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });

    server.use(
      http.get(BASE, () => HttpResponse.json([])),
      http.post(`${BASE}/setup-link`, () =>
        HttpResponse.json({
          url: `${ORIGIN}/p/card-setup/tok_abc`,
          token: "tok_abc",
          expires_at: "2026-08-09T00:00:00Z",
        })
      )
    );
    renderSection();

    await userEvent.click(
      await screen.findByRole("button", { name: /send card-on-file link/i })
    );

    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    expect(writeText).toHaveBeenCalledWith(`${ORIGIN}/p/card-setup/tok_abc`);
    // The expiry is part of the message: an operator who sits on the link needs
    // to know it goes stale.
    expect(toastSuccess).toHaveBeenCalledWith(
      "Card-on-file link copied",
      expect.objectContaining({
        description: expect.stringContaining("only be used once"),
      })
    );
  });

  it("confirms before removing a card and says what removal does", async () => {
    const removed = vi.fn();
    server.use(
      http.get(BASE, () => HttpResponse.json([savedCard()])),
      http.delete(`${BASE}/pm-row-1`, () => {
        removed();
        return HttpResponse.json(savedCard({ status: "removed" }));
      })
    );
    renderSection();

    await userEvent.click(
      await screen.findByRole("button", { name: /remove visa/i })
    );

    expect(
      await screen.findByText(/detached at Stripe and can no longer be charged/i)
    ).toBeInTheDocument();
    // Nothing has happened yet — the dialog is a real gate, not a formality.
    expect(removed).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: /remove card/i }));
    await waitFor(() => expect(removed).toHaveBeenCalledTimes(1));
    expect(toastSuccess).toHaveBeenCalledWith("Card removed");
  });

  it("surfaces the reason a removal failed instead of a generic error", async () => {
    server.use(
      http.get(BASE, () => HttpResponse.json([savedCard()])),
      http.delete(`${BASE}/pm-row-1`, () =>
        HttpResponse.json(
          { code: "not_found", message: "Payment method not found" },
          { status: 404 }
        )
      )
    );
    renderSection();

    await userEvent.click(
      await screen.findByRole("button", { name: /remove visa/i })
    );
    await userEvent.click(screen.getByRole("button", { name: /remove card/i }));

    await waitFor(() =>
      expect(toastError).toHaveBeenCalledWith("Payment method not found")
    );
  });
});
