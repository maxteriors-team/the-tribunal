import { expect, test } from "@playwright/test";

import { hasParallelTestUser, loginViaUI } from "./helpers";

/**
 * Appointment dialog smoke test.
 *
 * Opens the New Appointment dialog from the calendar page and verifies its
 * core fields render. Submission is attempted only when a contact is
 * available — otherwise we assert the validation error to keep the test
 * meaningful in empty workspaces. We intentionally do NOT pin the dialog to
 * a successful POST because creating an appointment requires a valid
 * contact_id that we cannot guarantee in every environment.
 */

test.describe("New Appointment dialog", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(
      !hasParallelTestUser(),
      "Configure per-worker E2E users or enable opt-in provisioning for the appointment flow",
    );
    await loginViaUI(page, testInfo);
  });

  test("opens dialog and surfaces validation when submitted empty", async ({ page }) => {
    await page.goto("/calendar");
    await expect(page.getByRole("heading", { name: "Calendar" })).toBeVisible();

    await page.getByRole("button", { name: /new appointment/i }).click();

    const dialog = page.getByRole("dialog", { name: /new appointment/i });
    await expect(dialog).toBeVisible();

    // Core form fields render.
    await expect(dialog.getByText(/contact \*/i)).toBeVisible();
    await expect(dialog.getByText(/date \*/i)).toBeVisible();
    await expect(dialog.getByText(/time \*/i)).toBeVisible();
    await expect(dialog.getByText(/duration/i)).toBeVisible();

    // Submit without selecting anything — schema requires contact + date +
    // time. Zod should block the submission and the dialog should remain
    // open with at least one validation message.
    await dialog.getByRole("button", { name: /^schedule$/i }).click();
    await expect(dialog).toBeVisible();

    // At least one required-field message should be visible.
    const errorCount = await dialog
      .locator("p")
      .filter({ hasText: /please select|required/i })
      .count();
    expect(errorCount).toBeGreaterThan(0);

    // Dialog can be dismissed via Cancel.
    await dialog.getByRole("button", { name: /cancel/i }).click();
    await expect(dialog).toBeHidden({ timeout: 5_000 });
  });
});
