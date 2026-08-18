import { expect, test } from "@playwright/test";

/**
 * Deployment liveness smoke tests for the frontend.
 *
 * These prove the deployed Next.js app is actually serving the SPA — not a
 * Vercel build error, a 404, or a blank white shell — without needing seeded
 * data or an authenticated session. Point them at any environment via
 * PLAYWRIGHT_BASE_URL (local dev, a Vercel preview, or production).
 *
 * Run only these:
 *   PLAYWRIGHT_BASE_URL=https://<app>.vercel.app npx playwright test smoke.spec.ts
 */
test.describe("Deployment smoke @smoke", () => {
  test("root URL serves the app and routes to a known page", async ({ page }) => {
    const response = await page.goto("/");

    // A reachable deployment returns an HTTP response with a non-error status
    // for the document. Build failures / outages surface as null or 5xx here.
    expect(response, "no HTTP response for /").not.toBeNull();
    expect(
      response!.status(),
      `root returned ${response!.status()}`,
    ).toBeLessThan(400);

    // Root redirects to /contacts; anonymous visitors are then sent to /login.
    // Either way the app must settle on a real route, not an error page.
    await expect(page).toHaveURL(
      /\/(login|contacts|onboarding|dashboard|realtor-dashboard)/,
    );
  });

  test("login route renders the app shell", async ({ page }) => {
    await page.goto("/login");

    // The login card copy only appears once React has mounted and rendered —
    // a server error or unstyled white screen would not contain it.
    await expect(page.getByText(/welcome back/i)).toBeVisible();
  });

  test("password recovery route stays public", async ({ page }) => {
    const response = await page.goto("/forgot-password");

    expect(response, "no HTTP response for /forgot-password").not.toBeNull();
    expect(response!.status()).toBeLessThan(400);
    await expect(page).toHaveURL(/\/forgot-password$/);
    await expect(page.getByRole("heading", { name: /reset your password/i })).toBeVisible();
  });
});
