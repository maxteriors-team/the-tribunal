import { test } from "@playwright/test";

import { APP_PAGES, capture } from "./pages";

/**
 * Capture the authenticated CRM surfaces. Runs with the stored session from
 * `auth.setup.ts` (configured via the project's `storageState`). One test per
 * page so a single failed capture never aborts the rest of the gallery.
 */
test.describe("visual · app", () => {
  for (const def of APP_PAGES) {
    test(def.title, async ({ page }, testInfo) => {
      await capture(page, def, testInfo);
    });
  }
});
