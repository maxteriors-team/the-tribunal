import { test } from "@playwright/test";

import { PUBLIC_PAGES, capture } from "./pages";

/**
 * Capture the public surfaces (no session required). One test per page so a
 * single failed capture never aborts the rest of the gallery.
 */
test.describe("visual · public", () => {
  for (const def of PUBLIC_PAGES) {
    test(def.title, async ({ page }, testInfo) => {
      await capture(page, def, testInfo);
    });
  }
});
