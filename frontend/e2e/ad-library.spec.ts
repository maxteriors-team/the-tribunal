import { expect, test } from "@playwright/test";

import { hasTestUser, loginViaUI } from "./helpers";

/**
 * Ad Library prospecting smoke test.
 *
 * Drives the ad-library UI end-to-end:
 *   1. Open /find-leads/ad-library.
 *   2. Confirm the ICP search form renders with the "consistent but not
 *      testing" toggles.
 *   3. Launch a search and confirm a job-status banner appears.
 *   4. Confirm the ranked advertiser results section + monitors panel render.
 *
 * Requires a seeded test user — skipped otherwise so the suite stays green in
 * minimal environments. To assert the ranked-results *table* (rather than the
 * empty state) seed tracked advertisers for the test user's workspace first:
 *
 *   cd backend && uv run python -m scripts.dev.seed_promote_e2e
 *
 * The results assertion below accepts either shape so the spec stays
 * deterministic whether or not advertisers are seeded.
 */

test.describe("Ad Library prospecting", () => {
  test.beforeEach(async ({ page }) => {
    test.skip(
      !hasTestUser(),
      "E2E_USER_EMAIL / E2E_USER_PASSWORD not set — skipping authenticated ad-library flow",
    );
    await loginViaUI(page);
  });

  test("search → results → monitors render", async ({ page }) => {
    await page.goto("/find-leads/ad-library");

    await expect(
      page.getByRole("heading", { name: /ad library/i }),
    ).toBeVisible({ timeout: 15_000 });

    // ICP toggles are the product differentiator — they must be present.
    await expect(page.getByText(/long-runner/i)).toBeVisible();
    await expect(page.getByText(/no testing/i)).toBeVisible();

    // --- SEARCH -------------------------------------------------------------
    await page.getByLabel(/keyword/i).first().fill("roofing");
    await page
      .getByRole("button", { name: /search ad library/i })
      .click();

    // A job-status banner appears once the search is enqueued (pending/running
    // or a terminal state). We assert on the status card region.
    await expect(
      page.getByText(/pending|running|succeeded|failed/i).first(),
    ).toBeVisible({ timeout: 20_000 });

    // The advertiser results toolbar renders the tracked-advertiser count.
    await expect(
      page.getByText(/\d+\s+advertisers/i).first(),
    ).toBeVisible({ timeout: 15_000 });

    // The results section renders deterministically as EITHER the ranked
    // table (when advertisers are seeded) or the empty state (when not).
    const resultsTable = page.getByRole("table");
    const emptyState = page.getByText(/no tracked advertisers yet/i);
    await expect(resultsTable.or(emptyState).first()).toBeVisible({
      timeout: 15_000,
    });

    // The saved-monitors panel is part of the page.
    await expect(page.getByText(/saved monitors/i)).toBeVisible();
  });
});
