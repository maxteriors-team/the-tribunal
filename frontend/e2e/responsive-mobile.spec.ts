import { expect, test, type Locator, type Page, type TestInfo } from "@playwright/test";

import { hasParallelTestUser, loginViaUI, uniqueSuffix } from "./helpers";

const hasAuthenticatedFixture = hasParallelTestUser();
const MOBILE_VIEWPORT = { width: 390, height: 844 } as const;

const mobileRoutes: Array<{
  name: string;
  path: string;
  heading: string;
  actions: (page: Page) => Locator[];
}> = [
  {
    name: "dashboard",
    path: "/dashboard",
    heading: "Dashboard",
    actions: (page) => [
      page.getByRole("link", { name: "New Campaign" }),
      page.getByRole("link", { name: "View Contacts" }),
    ],
  },
  {
    name: "assistant",
    path: "/assistant",
    heading: "CRM Assistant",
    actions: (page) => [
      page.getByRole("button", { name: "New chat" }),
      page.getByRole("button", { name: /Give me today's CRM briefing/ }),
    ],
  },
  {
    name: "opportunities",
    path: "/opportunities",
    heading: "Opportunities",
    actions: (page) => [
      page.getByRole("button", { name: "Manage stages" }),
      page.getByRole("button", { name: "Add Opportunity" }),
    ],
  },
  {
    name: "agents",
    path: "/agents",
    heading: "AI Agents",
    actions: (page) => [page.getByRole("link", { name: "Create Agent" })],
  },
  {
    name: "knowledge-base",
    path: "/knowledge",
    heading: "Knowledge Base",
    // The agent picker and Add Document only exist once the workspace owns an
    // agent — a fresh workspace correctly renders "No agents yet" instead.
    // Requiring them here failed the whole route audit, so the agent-dependent
    // chrome is asserted by the dedicated knowledge-base test below, which
    // seeds an agent. This entry still covers the route's layout in whichever
    // state the fixture is in.
    actions: () => [],
  },
  {
    name: "ai-suggestions",
    path: "/suggestions",
    heading: "AI Suggestions",
    actions: () => [],
  },
  {
    name: "reviews",
    path: "/reviews",
    heading: "Reviews & Reputation",
    actions: () => [],
  },
  {
    name: "service-plans",
    path: "/service-plans",
    heading: "Service Plans",
    actions: (page) => [page.getByRole("button", { name: /New service plan/i }).first()],
  },
  {
    name: "campaign-sms-stepper",
    path: "/campaigns/sms/new",
    heading: "Create SMS Campaign",
    actions: (page) => [page.getByRole("button", { name: "Next" })],
  },
  {
    name: "pre-booking-stepper",
    path: "/campaigns/pre-booking/new",
    heading: "Create Pre-Booking Campaign",
    actions: (page) => [page.getByRole("button", { name: "Next" })],
  },
  {
    name: "offers",
    path: "/offers",
    heading: "Offers",
    actions: (page) => [page.getByRole("button", { name: "Create Offer", exact: true })],
  },
  {
    name: "offer-stepper",
    path: "/offers/new",
    heading: "Create Offer",
    actions: (page) => [page.getByRole("button", { name: "Next" })],
  },
  {
    name: "settings-pricing",
    path: "/settings?tab=pricing",
    heading: "Settings",
    actions: (page) => [page.getByRole("button", { name: "Save financing settings" })],
  },
];

test.use({
  viewport: MOBILE_VIEWPORT,
  hasTouch: true,
  isMobile: true,
  colorScheme: "dark",
});

test.beforeEach(async ({ page }, testInfo) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  if (hasAuthenticatedFixture) {
    await loginViaUI(page, testInfo);
  }
});

async function openMobileRoute(page: Page, path: string, heading: string) {
  await page.goto(path);
  await expect(page).not.toHaveURL(/\/login(?:\?|$)/);
  await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
}

async function expectInsideViewport(locator: Locator) {
  const target = locator.first();
  await expect(target).toBeVisible();
  const box = await target.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.x).toBeGreaterThanOrEqual(-1);
  expect(box!.x + box!.width).toBeLessThanOrEqual(MOBILE_VIEWPORT.width + 1);
}

/** Fail if the current page overflows 390px or clips any interactive element. */
async function expectMobileLayoutIsClean(page: Page) {
  const layout = await page.evaluate(() => {
    const shellMain = document.querySelector("main");
    const isVisible = (element: Element) => {
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return (
        style.display !== "none" &&
        style.visibility !== "hidden" &&
        rect.width > 0 &&
        rect.height > 0
      );
    };
    const clippedInteractives = [
      ...document.querySelectorAll(
        'button, a, input, select, textarea, [role="button"], [role="tab"]',
      ),
    ]
      .filter(isVisible)
      .filter((element) => !element.closest('[data-slot="horizontal-scroll"]'))
      .map((element) => {
        const rect = element.getBoundingClientRect();
        return {
          label: (
            element.getAttribute("aria-label") ||
            element.textContent ||
            element.getAttribute("placeholder") ||
            "unnamed"
          )
            .trim()
            .replace(/\s+/g, " ")
            .slice(0, 80),
          left: Math.round(rect.left),
          right: Math.round(rect.right),
        };
      })
      .filter((rect) => rect.left < -1 || rect.right > window.innerWidth + 1);

    return {
      documentWidth: document.documentElement.scrollWidth,
      bodyWidth: document.body.scrollWidth,
      mainWidth: shellMain?.clientWidth ?? 0,
      mainScrollWidth: shellMain?.scrollWidth ?? 0,
      clippedInteractives,
    };
  });

  expect(layout.documentWidth).toBeLessThanOrEqual(MOBILE_VIEWPORT.width);
  expect(layout.bodyWidth).toBeLessThanOrEqual(MOBILE_VIEWPORT.width);
  expect(layout.mainScrollWidth).toBeLessThanOrEqual(layout.mainWidth + 1);
  expect(layout.clippedInteractives).toEqual([]);
}

async function attachMobileScreenshot(page: Page, testInfo: TestInfo, name: string) {
  await testInfo.attach(name, {
    body: await page.screenshot({ animations: "disabled" }),
    contentType: "image/png",
  });
}

/**
 * Create an agent through the API so the knowledge base leaves its "No agents
 * yet" state. Mirrors `seedTechnician` in time-attendance.spec.ts: `page.request`
 * carries the browser's auth cookies, and `/api/v1` is proxied to the backend by
 * the Next rewrite, so this follows PLAYWRIGHT_BASE_URL rather than pinning a port.
 */
async function seedAgent(page: Page) {
  const workspacesResponse = await page.request.get("/api/v1/workspaces");
  expect(workspacesResponse.ok(), await workspacesResponse.text()).toBeTruthy();
  const memberships = (await workspacesResponse.json()) as Array<{
    workspace: { id: string };
    is_default: boolean;
  }>;
  // Same precedence as workspace-provider, so the agent lands in the workspace
  // the dashboard actually renders. Seeding the wrong one fails loudly below:
  // the picker never appears.
  const workspaceId = (memberships.find((entry) => entry.is_default) ?? memberships[0])?.workspace
    .id;
  expect(workspaceId).toBeTruthy();

  const createResponse = await page.request.post(`/api/v1/workspaces/${workspaceId}/agents`, {
    data: {
      name: `Mobile Audit Agent ${uniqueSuffix()}`,
      system_prompt: "Answer home-service questions for the 390px responsive audit.",
    },
  });
  expect(createResponse.status(), await createResponse.text()).toBe(201);
}

test.describe("390px responsive shell", () => {
  test.skip(
    !hasAuthenticatedFixture,
    "Configure per-worker E2E users or enable opt-in provisioning for responsive routes.",
  );

  test("keeps target routes and primary actions inside the viewport, with mobile screenshots", async ({
    page,
  }, testInfo) => {
    test.setTimeout(120_000);

    for (const route of mobileRoutes) {
      await test.step(route.name, async () => {
        await openMobileRoute(page, route.path, route.heading);

        await expectMobileLayoutIsClean(page);

        for (const action of route.actions(page)) {
          await expectInsideViewport(action);
        }

        await attachMobileScreenshot(page, testInfo, `${route.name}-390`);
      });
    }
  });

  test("knowledge base fits 390px empty and with an agent selected", async ({ page }, testInfo) => {
    await openMobileRoute(page, "/knowledge", "Knowledge Base");

    // A provisioned workspace starts with no agents; a reused fixture account
    // may already own one. Pin whichever state this run opens in so the audit
    // can never pass against a spinner or the error card — neither renders a
    // heading or the picker. The generous timeout is for the agents query on a
    // cold dev server, not a softer assertion: "Loading agents…" still fails.
    const agentPicker = page.getByRole("combobox", { name: "Select an agent" });
    await expect(page.getByRole("heading", { name: "No agents yet" }).or(agentPicker)).toBeVisible({
      timeout: 30_000,
    });
    await expectMobileLayoutIsClean(page);
    await attachMobileScreenshot(page, testInfo, "knowledge-base-initial-390");

    await seedAgent(page);
    await page.reload();
    await expect(page.getByRole("heading", { level: 1, name: "Knowledge Base" })).toBeVisible({
      timeout: 30_000,
    });

    // The action state: both agent-dependent controls must be reachable, not
    // just rendered off the right edge.
    await expect(agentPicker).toBeVisible({ timeout: 30_000 });
    await expectInsideViewport(agentPicker);
    await expectInsideViewport(page.getByRole("button", { name: "Add Document" }));
    await expectMobileLayoutIsClean(page);
    await attachMobileScreenshot(page, testInfo, "knowledge-base-agent-390");
  });

  test("horizontal navigation exposes edge cues and scrolls by touch and keyboard", async ({
    context,
    page,
  }) => {
    await openMobileRoute(page, "/reviews", "Reviews & Reputation");

    const scroller = page.getByTestId("reviews-tabs-scroll");
    await scroller.evaluate((element) => element.scrollIntoView({ block: "center" }));
    await expect(scroller).toHaveAttribute("data-scroll-right", "true");
    await expect(scroller.locator("xpath=..//*[@data-slot='horizontal-scroll-cue']")).toBeVisible();

    const box = await scroller.boundingBox();
    expect(box).not.toBeNull();
    const session = await context.newCDPSession(page);
    const y = box!.y + box!.height / 2;
    const startX = box!.x + box!.width - 24;
    const endX = box!.x + 32;

    await session.send("Input.dispatchTouchEvent", {
      type: "touchStart",
      touchPoints: [{ x: startX, y, radiusX: 1, radiusY: 1 }],
    });
    for (let step = 1; step <= 4; step += 1) {
      const x = startX + ((endX - startX) * step) / 4;
      await session.send("Input.dispatchTouchEvent", {
        type: "touchMove",
        touchPoints: [{ x, y, radiusX: 1, radiusY: 1 }],
      });
      await page.waitForTimeout(25);
    }
    await session.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
    await expect.poll(() => scroller.evaluate((element) => element.scrollLeft)).toBeGreaterThan(10);

    await scroller.evaluate((element) => element.scrollTo({ left: 0 }));
    await scroller.focus();
    await expect(scroller).toBeFocused();
    await page.keyboard.press("ArrowRight");
    await expect.poll(() => scroller.evaluate((element) => element.scrollLeft)).toBeGreaterThan(0);
  });

  test("wrapped opportunity action activates with touch and keyboard", async ({ page }) => {
    await openMobileRoute(page, "/opportunities", "Opportunities");

    const addOpportunity = page.getByRole("button", { name: "Add Opportunity" });
    await addOpportunity.tap();
    await expect(
      page.getByRole("dialog").getByRole("heading", { name: "Add Opportunity" }),
    ).toBeVisible();
    const dialog = page.getByRole("dialog");
    await dialog.getByRole("button", { name: "Close" }).click();
    await expect(dialog).toBeHidden();

    await addOpportunity.focus();
    await page.keyboard.press("Enter");
    await expect(
      page.getByRole("dialog").getByRole("heading", { name: "Add Opportunity" }),
    ).toBeVisible();
  });

  test("assistant starter prompts wrap instead of clipping", async ({ page }) => {
    await openMobileRoute(page, "/assistant", "CRM Assistant");

    const prompt = page.getByRole("button", {
      name: /Schedule a calendar appointment for a contact/,
    });
    await expectInsideViewport(prompt);
    const metrics = await prompt.evaluate((element) => ({
      clientWidth: element.clientWidth,
      clientHeight: element.clientHeight,
      scrollWidth: element.scrollWidth,
    }));
    expect(metrics.scrollWidth).toBeLessThanOrEqual(metrics.clientWidth + 1);
    expect(metrics.clientHeight).toBeGreaterThan(36);
  });
});
