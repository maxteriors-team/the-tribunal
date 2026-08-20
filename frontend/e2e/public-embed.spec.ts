import { expect, test, type FrameLocator, type Page } from "@playwright/test";

const APP_ORIGIN = process.env.PLAYWRIGHT_BASE_URL || "http://localhost:3000";
// Both parents are served by the real local Next process. Chromium's Local
// Network Access checks intentionally block a mocked public host from framing
// localhost before the iframe request can exercise application code.
const ALLOWED_PARENT_ORIGIN = "http://127.0.0.1:3000";
const UNAUTHORIZED_PARENT_ORIGIN = APP_ORIGIN;
const VALID_PUBLIC_ID = "public-agent-e2e";
const INVALID_PUBLIC_ID = "missing-agent-e2e";
const PARENT_ORIGIN_HEADER = "x-embed-parent-origin";

const EMBED_ROUTES = [
  { suffix: "", readyText: "Open QA Agent" },
  { suffix: "/chat", readyText: "Open QA Agent" },
  { suffix: "/both", readyText: "Public Embed QA" },
  { suffix: "/fullpage", readyText: "Public Embed QA" },
] as const;

const CONFIG_FIXTURE = {
  public_id: VALID_PUBLIC_ID,
  name: "Public Embed QA",
  greeting_message: "Embed fixture ready",
  button_text: "Open QA Agent",
  theme: "light",
  position: "bottom-right",
  primary_color: "#2563eb",
  language: "en-US",
  voice: "ash",
  channel_mode: "both",
};

interface EmbedApiMock {
  authProbeCount: () => number;
  claimedParentOrigins: () => string[];
}

async function installEmbedApiMock(page: Page): Promise<EmbedApiMock> {
  let authRequests = 0;
  const parentOrigins: string[] = [];

  await page.route("**/api/v1/auth/me", async (route) => {
    authRequests += 1;
    await route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Not authenticated" }),
    });
  });

  await page.route("**/api/v1/p/embed/*/config", async (route) => {
    const request = route.request();
    const publicId = new URL(request.url()).pathname.split("/").at(-2);
    const parentOrigin = request.headers()[PARENT_ORIGIN_HEADER] ?? "";
    parentOrigins.push(parentOrigin);

    if (publicId === INVALID_PUBLIC_ID) {
      await route.fulfill({
        status: 404,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Agent not found" }),
      });
      return;
    }

    if (parentOrigin !== ALLOWED_PARENT_ORIGIN) {
      await route.fulfill({
        status: 403,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Parent origin not allowed" }),
      });
      return;
    }

    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(CONFIG_FIXTURE),
    });
  });

  return {
    authProbeCount: () => authRequests,
    claimedParentOrigins: () => parentOrigins,
  };
}

async function openHostedEmbed(
  page: Page,
  parentOrigin: string,
  publicId: string,
  suffix: string,
): Promise<FrameLocator> {
  const embedUrl = `${APP_ORIGIN}/embed/${publicId}${suffix}`;

  // Establish a real loopback origin without booting the dashboard React tree,
  // then replace the harmless robots document with a customer-style iframe.
  await page.goto(`${parentOrigin}/robots.txt`);
  await page.setContent(`<!doctype html>
    <html lang="en">
      <body>
        <iframe title="Agent embed" src="${embedUrl}" allow="microphone"></iframe>
      </body>
    </html>`);
  return page.frameLocator('iframe[title="Agent embed"]');
}

function expectOnlyParentOrigin(api: EmbedApiMock, expectedOrigin: string): void {
  const claims = api.claimedParentOrigins();
  expect(claims.length).toBeGreaterThan(0);
  expect(claims.every((claim) => claim === expectedOrigin)).toBe(true);
}

for (const embedRoute of EMBED_ROUTES) {
  const routeLabel = embedRoute.suffix || "/embed/[publicId]";

  test(`${routeLabel} loads anonymously on an allowed parent domain`, async ({ page }) => {
    const api = await installEmbedApiMock(page);
    const frame = await openHostedEmbed(
      page,
      ALLOWED_PARENT_ORIGIN,
      VALID_PUBLIC_ID,
      embedRoute.suffix,
    );

    await expect(frame.getByText(embedRoute.readyText, { exact: true }).first()).toBeVisible();
    expectOnlyParentOrigin(api, ALLOWED_PARENT_ORIGIN);
    expect(api.authProbeCount()).toBe(0);
  });

  test(`${routeLabel} keeps an invalid public id anonymous`, async ({ page }) => {
    const api = await installEmbedApiMock(page);
    const frame = await openHostedEmbed(
      page,
      ALLOWED_PARENT_ORIGIN,
      INVALID_PUBLIC_ID,
      embedRoute.suffix,
    );

    await expect(frame.getByText("Agent not found", { exact: true })).toBeVisible();
    expectOnlyParentOrigin(api, ALLOWED_PARENT_ORIGIN);
    expect(api.authProbeCount()).toBe(0);
  });

  test(`${routeLabel} rejects an unauthorized parent domain without login`, async ({ page }) => {
    const api = await installEmbedApiMock(page);
    const frame = await openHostedEmbed(
      page,
      UNAUTHORIZED_PARENT_ORIGIN,
      VALID_PUBLIC_ID,
      embedRoute.suffix,
    );

    await expect(frame.getByText("Parent origin not allowed", { exact: true })).toBeVisible();
    expectOnlyParentOrigin(api, UNAUTHORIZED_PARENT_ORIGIN);
    expect(api.authProbeCount()).toBe(0);
  });
}
