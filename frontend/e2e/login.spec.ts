import { expect, test } from "@playwright/test";

import { canProvisionUsers, hasTestUser, loginViaUI, uniqueSuffix } from "./helpers";

/**
 * Auth + workspace bootstrap.
 *
 * Two scenarios are exercised:
 *   1. Anonymous signup — visit /register, submit signup, expect workspace
 *      creation / onboarding hand-off.
 *   2. Existing-user login — drive /login with seeded credentials and assert
 *      the user lands on an authenticated page (dashboard / onboarding /
 *      contacts depending on workspace state).
 *
 * Signup mutates backend state, so it runs only when provisioning is explicitly
 * enabled. Read-only login checks remain safe in public-only environments.
 */

test.describe("Authentication", () => {
  test("login form is reachable", async ({ page }) => {
    await page.goto("/login");
    await expect(page.getByText(/welcome back/i)).toBeVisible();
    await expect(page.getByLabel(/email/i)).toBeVisible();
    await expect(page.getByLabel(/password/i)).toBeVisible();
    await expect(page.getByRole("button", { name: /sign in/i })).toBeVisible();
  });

  test("invalid credentials surface an inline error", async ({ page }) => {
    await page.route("**/api/v1/auth/login", async (route) => {
      await route.fulfill({
        status: 401,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Incorrect email or password" }),
      });
    });
    await page.goto("/login");
    await page.getByLabel(/email/i).fill(`nobody-${uniqueSuffix()}@example.com`);
    await page.getByLabel(/password/i).fill("definitely-wrong-password");
    await page.getByRole("button", { name: /sign in/i }).click();

    await expect(page).toHaveURL(/\/login/);
    await expect(page.locator("#login-error")).toContainText("Email or password is incorrect");
  });

  test("signup → workspace creation → dashboard", async ({ page }) => {
    test.skip(
      !canProvisionUsers(),
      "Set E2E_ALLOW_PROVISIONING=1 to exercise account creation against this backend",
    );
    await page.goto("/register");

    await expect(page.getByText(/create your account/i)).toBeVisible();

    const suffix = uniqueSuffix();
    await page.getByLabel(/full name/i).fill("Signup E2E");
    await page.getByLabel(/email/i).fill(`e2e-${suffix}@example.com`);
    await page.getByLabel(/password/i).fill(`Test-${suffix}-Pass!`);

    const submit = page
      .getByRole("button", { name: /sign up|create account|get started/i })
      .first();
    await submit.click();

    // Successful signup should land on onboarding or the dashboard, not the
    // signup page.
    await expect(page).not.toHaveURL(/\/register$/, { timeout: 15_000 });
    await expect(page).toHaveURL(/\/(onboarding|dashboard|realtor-dashboard|contacts|\/?$)/);
  });

  test("seeded user can log in and reach an authenticated page", async ({ page }) => {
    test.skip(
      !hasTestUser(),
      "E2E_USER_EMAIL / E2E_USER_PASSWORD not set — skipping authenticated login",
    );

    await loginViaUI(page);

    // After login the app should NOT show the login form.
    await expect(page.getByText(/welcome back/i)).toHaveCount(0);
  });
});
