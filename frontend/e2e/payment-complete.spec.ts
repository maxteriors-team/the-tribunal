import { expect, test } from "@playwright/test";

const VERIFY_ROUTE = "**/api/v1/p/payments/checkout-sessions/*/verify";

test.describe("payment completion verification", () => {
  test("rechecks a pending Checkout session until Stripe confirms payment", async ({ page }) => {
    let verificationRequests = 0;
    let stripeHasConfirmedPayment = false;

    await page.route(VERIFY_ROUTE, async (route) => {
      verificationRequests += 1;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          status: stripeHasConfirmedPayment ? "paid" : "pending",
        }),
      });
    });

    await page.goto("/payment-complete?session_id=cs_test_verified");

    await expect(page.getByRole("heading", { name: "Payment processing" })).toBeVisible();
    stripeHasConfirmedPayment = true;
    await page.getByRole("button", { name: "Check again" }).click();
    await expect(page.getByRole("heading", { name: "Payment received" })).toBeVisible();
    await expect(page.getByText("Stripe confirmed your payment successfully.")).toBeVisible();
    expect(verificationRequests).toBeGreaterThanOrEqual(2);
  });

  test("never shows success when verification fails", async ({ page }) => {
    await page.route(VERIFY_ROUTE, async (route) => {
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Payment provider unavailable" }),
      });
    });

    await page.goto("/payment-complete?session_id=cs_test_unavailable");

    await expect(
      page.getByRole("heading", { name: "We couldn't verify this payment" }),
    ).toBeVisible();
    await expect(page.getByText("Payment received", { exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Try again" })).toBeVisible();
  });

  test("requires a Checkout session id before calling verification", async ({ page }) => {
    let verificationRequests = 0;
    await page.route(VERIFY_ROUTE, async (route) => {
      verificationRequests += 1;
      await route.abort();
    });

    await page.goto("/payment-complete");

    await expect(page.getByRole("heading", { name: "Payment not verified" })).toBeVisible();
    expect(verificationRequests).toBe(0);
  });
});
