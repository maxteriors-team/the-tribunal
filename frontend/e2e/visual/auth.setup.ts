import { test as setup } from "@playwright/test";

import { AUTH_FILE, authenticate } from "./pages";

/**
 * Auth bootstrap for the authenticated visual projects. Logs in once and saves
 * the session to `.auth/state.json`; `app-desktop` / `app-mobile` depend on
 * this project and load that storage state. Only runs when a seeded user is
 * configured (the config omits these projects otherwise).
 */
setup("authenticate", async ({ page }) => {
  await authenticate(page, AUTH_FILE);
});
