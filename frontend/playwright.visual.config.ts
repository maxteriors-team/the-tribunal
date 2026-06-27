import { defineConfig, devices } from "@playwright/test";

import { AUTH_FILE } from "./e2e/visual/pages";

/**
 * Visual-preview Playwright config — separate from `playwright.config.ts` so
 * the functional e2e suite and the screenshot suite stay independent (different
 * test files, output dir, viewports, and reporters).
 *
 * Captures full-page screenshots of key screens at desktop + mobile widths and
 * writes them to `visual-snapshots/<project>/<slug>.png`, which the gallery
 * builder turns into a browsable `index.html`. Run via `npm run visual`.
 *
 * Authenticated projects are included only when E2E_USER_EMAIL /
 * E2E_USER_PASSWORD are set; otherwise just the public surfaces are captured so
 * the suite still produces a gallery in minimal environments.
 */
const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3000";
const isCI = !!process.env.CI;
const hasUser = !!(process.env.E2E_USER_EMAIL && process.env.E2E_USER_PASSWORD);

const desktop = { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } };
const mobile = { ...devices["Pixel 7"] };

export default defineConfig({
  testDir: "./e2e/visual",
  // Screenshots are deterministic paths; the run output (traces/videos) is
  // kept separate from the gallery PNGs.
  outputDir: "./visual-snapshots/.pw-output",
  fullyParallel: false,
  forbidOnly: isCI,
  retries: isCI ? 1 : 0,
  // Serial so screenshots are written in a predictable order and the dev/prod
  // server isn't hammered by parallel full-page captures.
  workers: 1,
  timeout: 90_000,
  reporter: isCI
    ? [["github"], ["html", { outputFolder: "playwright-report", open: "never" }]]
    : [["list"], ["html", { outputFolder: "playwright-report", open: "never" }]],

  use: {
    baseURL,
    trace: "on-first-retry",
  },

  projects: [
    {
      name: "public-desktop",
      testMatch: /public\.visual\.ts$/,
      use: desktop,
    },
    {
      name: "public-mobile",
      testMatch: /public\.visual\.ts$/,
      use: mobile,
    },
    ...(hasUser
      ? [
          {
            name: "setup",
            testMatch: /auth\.setup\.ts$/,
            use: desktop,
          },
          {
            name: "app-desktop",
            testMatch: /app\.visual\.ts$/,
            use: { ...desktop, storageState: AUTH_FILE },
            dependencies: ["setup"],
          },
          {
            name: "app-mobile",
            testMatch: /app\.visual\.ts$/,
            use: { ...mobile, storageState: AUTH_FILE },
            dependencies: ["setup"],
          },
        ]
      : []),
  ],

  /**
   * When PLAYWRIGHT_BASE_URL is set we target an already-running server (CI
   * boots `next start` itself, or you point at a remote env). Otherwise boot a
   * production build locally — visual captures must run against `next start`,
   * not `next dev`, for deterministic, fully-hydrated renders.
   */
  webServer: process.env.PLAYWRIGHT_BASE_URL
    ? undefined
    : {
        command: "npm run start",
        url: baseURL,
        reuseExistingServer: !isCI,
        timeout: 120_000,
      },
});
