import { randomUUID } from "node:crypto";

import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright configuration for The Tribunal CRM frontend.
 *
 * `baseURL` is taken from the PLAYWRIGHT_BASE_URL environment variable so that
 * the same suite can run against a local dev server, a Vercel preview, or a
 * Railway staging environment without code changes. The default mirrors the
 * Next.js dev server port (`npm run dev`).
 *
 * See https://playwright.dev/docs/test-configuration.
 */
const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3000";
const isCI = !!process.env.CI;

// Set once in the runner process, then inherit it in every Playwright worker.
// Provisioned accounts combine this run id with `parallelIndex`, so no worker
// logs into another worker's rotating refresh-token session.
process.env.E2E_RUN_ID ??= randomUUID();

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: isCI,
  retries: isCI ? 2 : 0,
  // Cold Turbopack route compilation competes across normal parallel workers.
  timeout: 60_000,
  // Keep Playwright's normal worker count. Authenticated specs either provision
  // one account per parallel worker or use an explicitly indexed account pool.
  reporter: isCI ? [["github"], ["html", { open: "never" }]] : "list",

  use: {
    baseURL,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },

  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        // Roomy viewport so multi-column dialog layouts render the way an
        // operator sees them on a laptop. Form dialogs no longer *need* the
        // height: `FormDialog` caps itself at the viewport and scrolls its
        // fields, keeping the header and the Cancel/Submit footer pinned.
        viewport: { width: 1280, height: 1100 },
      },
    },
  ],

  /**
   * When PLAYWRIGHT_BASE_URL is set we assume the dev server is already
   * running (or we are pointing at a remote environment) and skip booting
   * `next dev` ourselves.
   */
  webServer: process.env.PLAYWRIGHT_BASE_URL
    ? undefined
    : {
        command: "npm run dev",
        url: baseURL,
        reuseExistingServer: !isCI,
        timeout: 120_000,
        stdout: "pipe",
        stderr: "pipe",
      },
});
