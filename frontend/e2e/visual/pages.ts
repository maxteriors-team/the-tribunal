import { type Page, type TestInfo, expect } from "@playwright/test";

/**
 * Shared page catalogue + capture helper for the visual-preview suite.
 *
 * Each push runs this against a real, booted stack and writes a full-page PNG
 * per page per viewport into `visual-snapshots/<project>/<slug>.png`. Those are
 * assembled into a browsable gallery (see `scripts/build-visual-gallery.mjs`)
 * and surfaced as a CI artifact + job summary so reviewers can *see* how every
 * screen looks after a change — not just read a green check.
 */

/**
 * Where the authenticated session is persisted by `auth.setup.ts` and reloaded
 * by the app capture projects. Defined here (a non-test module) so the
 * Playwright config can import it without pulling in a file that calls test().
 */
export const AUTH_FILE = ".auth/state.json";

export interface VisualPage {
  /** Filename-safe id; also the gallery section key. */
  slug: string;
  /** Human label shown in the gallery + job summary. */
  title: string;
  /** Route to visit, relative to baseURL. */
  path: string;
}

/**
 * Public surfaces — render without a session, so they are always captured even
 * when no seeded user is available.
 */
export const PUBLIC_PAGES: VisualPage[] = [
  { slug: "login", title: "Login", path: "/login" },
  { slug: "landing", title: "Landing page", path: "/p/landing" },
];

/**
 * Authenticated CRM surfaces — captured only when a seeded user is configured
 * (see `auth.setup.ts`). Kept to the core operator screens so a push preview
 * stays under a few minutes; add high-traffic pages here as they stabilise.
 */
export const APP_PAGES: VisualPage[] = [
  { slug: "today", title: "Today", path: "/today" },
  { slug: "contacts", title: "Contacts", path: "/contacts" },
  { slug: "opportunities", title: "Opportunities", path: "/opportunities" },
  { slug: "campaigns", title: "Campaigns", path: "/campaigns" },
  { slug: "calendar", title: "Calendar", path: "/calendar" },
  { slug: "pending-actions", title: "Pending actions", path: "/pending-actions" },
  { slug: "offers", title: "Offers", path: "/offers" },
  { slug: "settings", title: "Settings", path: "/settings" },
];

/**
 * Navigate to a page, let it settle, and write a deterministic full-page
 * screenshot. The shot is also attached to the Playwright HTML report so it
 * renders inline there as a second viewer.
 *
 * Capture is intentionally tolerant: we wait for the network to go idle and for
 * any route-level loading spinner to disappear, but we do NOT assert specific
 * copy. A page that renders an error state still gets captured — surfacing a
 * regression visually is the whole point.
 */
export async function capture(
  page: Page,
  def: VisualPage,
  testInfo: TestInfo,
): Promise<void> {
  await page.goto(def.path, { waitUntil: "networkidle", timeout: 45_000 });

  // Wait out the app's route-level loading spinner (the auth/workspace
  // providers render one until the session resolves). Best-effort — if it was
  // never shown or already gone, we move on rather than fail the capture.
  await page
    .locator('[role="status"], .animate-spin')
    .first()
    .waitFor({ state: "hidden", timeout: 15_000 })
    .catch(() => {});

  // Settle late layout shifts / entrance animations before the shot.
  await page.waitForTimeout(800);

  const path = `visual-snapshots/${testInfo.project.name}/${def.slug}.png`;
  await page.screenshot({ path, fullPage: true, animations: "disabled" });
  await testInfo.attach(`${def.title} (${testInfo.project.name})`, {
    path,
    contentType: "image/png",
  });
}

/**
 * Sign in through the real login form, settle the first-run onboarding gate,
 * and persist the session to `authFile` so the authenticated capture projects
 * can reuse it. Shared by `auth.setup.ts`.
 */
export async function authenticate(page: Page, authFile: string): Promise<void> {
  const email = process.env.E2E_USER_EMAIL;
  const password = process.env.E2E_USER_PASSWORD;
  if (!email || !password) {
    throw new Error(
      "authenticate() requires E2E_USER_EMAIL / E2E_USER_PASSWORD to be set",
    );
  }

  await page.goto("/login");
  // The login card title renders as a styled <div>, not a heading.
  await expect(page.getByText(/welcome back/i)).toBeVisible({ timeout: 30_000 });
  await page.getByLabel(/email/i).fill(email);
  await page.getByLabel(/password/i).fill(password);
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page).not.toHaveURL(/\/login$/, { timeout: 30_000 });

  await settleOnboardingGate(page);
  await page.context().storageState({ path: authFile });
}

/**
 * A brand-new workspace (no AI agent yet) is force-redirected to `/onboarding`
 * exactly once, and the gate records that in `localStorage` keyed by workspace
 * id. We land in the app once so that flag is written, then persist it into the
 * saved session — otherwise every authenticated capture would re-trigger the
 * redirect and screenshot the onboarding wizard instead of the real page.
 *
 * We also dismiss the first-run "finish setup" banner for the same workspace so
 * captures show the page chrome cleanly. If the workspace is already onboarded
 * the gate writes nothing and this is a no-op.
 */
async function settleOnboardingGate(page: Page): Promise<void> {
  await page.goto("/contacts");
  await page
    .waitForFunction(
      () =>
        Object.keys(window.localStorage).some((k) =>
          k.startsWith("onboarding_autoredirected:"),
        ),
      undefined,
      { timeout: 20_000 },
    )
    .catch(() => {});
  await page.evaluate(() => {
    for (const key of Object.keys(window.localStorage)) {
      if (key.startsWith("onboarding_autoredirected:")) {
        const id = key.slice("onboarding_autoredirected:".length);
        window.localStorage.setItem(`onboarding_card_dismissed:${id}`, "1");
      }
    }
  });
}
