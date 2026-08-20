import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { publicPaymentsApi } from "@/lib/api/public-payments";

import PaymentCompletePage from "./page";

vi.mock("@/lib/api/public-payments", () => ({
  publicPaymentsApi: {
    verify: vi.fn(),
  },
}));

const verifyPayment = vi.mocked(publicPaymentsApi.verify);

async function renderUrl(url: string) {
  const parsedUrl = new URL(url, "https://example.test");
  const sessionIds = parsedUrl.searchParams.getAll("session_id");
  const sessionId =
    sessionIds.length > 1 ? sessionIds : sessionIds.length === 1 ? sessionIds[0] : undefined;
  const page = await PaymentCompletePage({
    searchParams: Promise.resolve({ session_id: sessionId }),
  });
  return act(async () => render(page));
}

describe("payment-complete URL verification", () => {
  beforeEach(() => {
    verifyPayment.mockReset();
  });

  it("shows a valid URL as paid only after backend verification", async () => {
    let resolveVerification!: (value: { status: "paid" }) => void;
    verifyPayment.mockReturnValue(
      new Promise((resolve) => {
        resolveVerification = resolve;
      }),
    );

    await renderUrl("/payment-complete?session_id=cs_test_valid123");

    expect(screen.getByRole("heading", { name: "Checking payment" })).toBeInTheDocument();
    expect(screen.queryByText("Payment received")).not.toBeInTheDocument();

    await act(async () => {
      resolveVerification({ status: "paid" });
    });

    expect(screen.getByRole("heading", { name: "Payment received" })).toBeInTheDocument();
    expect(verifyPayment).toHaveBeenCalledWith("cs_test_valid123", expect.any(AbortSignal));
  });

  it("renders an invalid session URL as a retryable verification failure", async () => {
    verifyPayment.mockRejectedValueOnce(new Error("404"));

    await renderUrl("/payment-complete?session_id=cs_test_invalid123");

    expect(
      await screen.findByRole("heading", { name: "We couldn't verify this payment" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    expect(screen.queryByText("Payment received")).not.toBeInTheDocument();
  });

  it("renders an expired session URL without claiming payment", async () => {
    verifyPayment.mockResolvedValue({ status: "expired" });

    await renderUrl("/payment-complete?session_id=cs_test_expired123");

    expect(
      await screen.findByRole("heading", { name: "Payment link expired" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Payment received")).not.toBeInTheDocument();
  });

  it("re-verifies a replayed paid URL and keeps the result truthful", async () => {
    verifyPayment.mockResolvedValue({ status: "paid" });
    const url = "/payment-complete?session_id=cs_test_replayed123";

    const firstVisit = await renderUrl(url);
    expect(await screen.findByRole("heading", { name: "Payment received" })).toBeInTheDocument();
    firstVisit.unmount();

    await renderUrl(url);
    expect(await screen.findByRole("heading", { name: "Payment received" })).toBeInTheDocument();
    expect(verifyPayment).toHaveBeenCalledTimes(2);
  });

  it("rejects a missing-session URL without calling the backend", async () => {
    await renderUrl("/payment-complete");

    expect(screen.getByRole("heading", { name: "Payment not verified" })).toBeInTheDocument();
    expect(screen.queryByText("Payment received")).not.toBeInTheDocument();
    expect(verifyPayment).not.toHaveBeenCalled();
  });

  it("renders pending state and retries verification on demand", async () => {
    verifyPayment
      .mockResolvedValueOnce({ status: "pending" })
      .mockResolvedValueOnce({ status: "paid" });
    const user = userEvent.setup();

    await renderUrl("/payment-complete?session_id=cs_test_pending123");

    expect(await screen.findByRole("heading", { name: "Payment processing" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Check again" }));

    expect(await screen.findByRole("heading", { name: "Payment received" })).toBeInTheDocument();
    expect(verifyPayment).toHaveBeenCalledTimes(2);
  });
});
