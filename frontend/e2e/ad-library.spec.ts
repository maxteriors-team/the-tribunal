import { expect, test } from "@playwright/test";

import { hasParallelTestUser, loginViaUI } from "./helpers";

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
 * Requires one isolated user per worker — skipped when an account pool or
 * opt-in provisioning is absent. To assert the ranked-results *table* (rather than the
 * empty state) seed tracked advertisers for the test user's workspace first:
 *
 *   cd backend && uv run python -m scripts.dev.seed_promote_e2e
 *
 * The results assertion below accepts either shape so the spec stays
 * deterministic whether or not advertisers are seeded.
 */

test.describe("Ad Library prospecting", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(
      !hasParallelTestUser(),
      "Configure per-worker E2E users or enable opt-in provisioning for the ad-library flow",
    );
    await loginViaUI(page, testInfo);
  });

  test("search → results → monitors render", async ({ page }) => {
    await page.goto("/find-leads/ad-library");

    await expect(page.getByRole("heading", { name: /ad library/i })).toBeVisible({
      timeout: 15_000,
    });

    // ICP toggles are the product differentiator — they must be present.
    await expect(page.getByText(/long-runner/i)).toBeVisible();
    await expect(page.getByText(/no testing/i)).toBeVisible();

    // --- SEARCH -------------------------------------------------------------
    await page
      .getByLabel(/keyword/i)
      .first()
      .fill("roofing");
    const searchResponsePromise = page.waitForResponse(
      (response) =>
        /\/ad-library\/search$/.test(response.url()) && response.request().method() === "POST",
    );
    await page.getByRole("button", { name: /search ad library/i }).click();
    const searchResponse = await searchResponsePromise;

    // Missing provider credentials are an actionable setup state. The form and
    // the rest of the module must remain usable instead of hitting the route
    // error boundary.
    if (searchResponse.status() === 503) {
      await expect(searchResponse.json()).resolves.toMatchObject({
        code: "ad_library_provider_unavailable",
      });
      await expect(page.getByText("Ad Library needs a provider token")).toBeVisible();
      await expect(page.getByRole("link", { name: "Open Settings" })).toHaveAttribute(
        "href",
        "/settings?tab=integrations",
      );
      await expect(page.getByRole("heading", { name: "Ad Library", exact: true })).toBeVisible();
      await expect(page.getByText(/saved monitors/i)).toBeVisible();
      return;
    }

    expect(searchResponse.status(), "ad-library search should start").toBeLessThan(300);

    // A job-status banner appears once the search is enqueued (pending/running
    // or a terminal state). We assert on the status card region.
    await expect(page.getByText(/pending|running|succeeded|failed/i).first()).toBeVisible({
      timeout: 20_000,
    });

    // The advertiser results toolbar renders the tracked-advertiser count.
    await expect(page.getByText(/\d+\s+advertisers/i).first()).toBeVisible({
      timeout: 15_000,
    });

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
