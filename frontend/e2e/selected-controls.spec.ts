import { expect, test, type CDPSession, type Locator, type Page } from "@playwright/test";

import type { Contact } from "../src/types/contact";

const workspaceId = "11111111-1111-4111-8111-111111111111";
const stamp = "2026-09-10T12:00:00Z";
const statuses = ["new", "contacted", "qualified", "converted", "lost"] as const;
const statusNames = ["All 5", "New 1", "Contacted 1", "Qualified 1", "Converted 1", "Lost 1"];
const modeNames = ["AI agent", "Me (human rep)"];

// Real pages and API clients; synthetic responses only, with external requests blocked.
async function fixture(page: Page) {
  const requests: { method: string; path: string; status: string | null }[] = [];
  const workspace = {
    id: workspaceId,
    name: "Synthetic selection workspace",
    slug: "selection-e2e",
    settings: { timezone: "America/New_York" },
    onboarding_completed_at: stamp,
    is_active: true,
    created_at: stamp,
    updated_at: stamp,
  };
  const contacts: Contact[] = statuses.map((status, index) => ({
    id: index + 1,
    user_id: 999999,
    workspace_id: workspaceId,
    first_name: `Synthetic ${status}`,
    status,
    created_at: stamp,
    updated_at: stamp,
  }));
  const prefix = `/api/v1/workspaces/${workspaceId}`;
  const responses: Record<string, unknown> = {
    "/api/v1/auth/me": {
      id: 999999,
      email: "selection@example.invalid",
      full_name: "Synthetic operator",
      is_active: true,
      default_workspace_id: workspaceId,
      created_at: stamp,
    },
    "/api/v1/workspaces": [{ workspace, role: "owner", is_default: true }],
    [prefix]: workspace,
    [`${prefix}/contacts/stats`]: {
      new_leads_30d: 5,
      new_leads_change: "+0%",
      new_clients_30d: 1,
      new_clients_change: "+0%",
      total_new_clients_ytd: 1,
    },
    [`${prefix}/agents`]: {
      items: [{ id: "agent", name: "Synthetic rep", is_active: true }],
      total: 1,
      page: 1,
      page_size: 50,
      pages: 1,
    },
    [`${prefix}/roleplay/personas`]: [
      {
        id: "persona",
        name: "Synthetic prospect",
        difficulty: "medium",
        objections: [],
        is_builtin: true,
      },
    ],
    [`${prefix}/roleplay/runs`]: [],
    [`${prefix}/lead-sources`]: [],
    [`${prefix}/lead-source-capture`]: { require_lead_source_on_manual_create: false },
    [`${prefix}/tags`]: [],
    [`${prefix}/custom-fields`]: [],
    [`${prefix}/custom-fields/definitions`]: [],
    [`${prefix}/conversations/unread-summary`]: { unread_conversations: 0, unread_messages: 0 },
    [`${prefix}/nudges/stats`]: { pending: 0, snoozed: 0, completed: 0, dismissed: 0 },
    [`${prefix}/pending-actions/stats`]: {
      pending: 0,
      approved: 0,
      rejected: 0,
      expired: 0,
      total: 0,
    },
    [`${prefix}/notifications/unread-count`]: { count: 0 },
  };
  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (!url.pathname.startsWith("/api/")) {
      return ["localhost", "127.0.0.1"].includes(url.hostname)
        ? route.continue()
        : route.abort("blockedbyclient");
    }
    const path = url.pathname.replace(/\/$/, "");
    const status = url.searchParams.get("status");
    // Track these controls' domains, not the shell's independent phone registration.
    if (path.startsWith(`${prefix}/contacts`) || path.startsWith(`${prefix}/roleplay`)) {
      requests.push({ method: request.method(), path, status });
    }
    if (path === `${prefix}/contacts`) {
      const items = contacts.filter((contact) => !status || contact.status === status);
      return route.fulfill({
        json: {
          items,
          total: items.length,
          page: 1,
          page_size: 25,
          pages: 1,
          status_counts: { all: 5, new: 1, contacted: 1, qualified: 1, converted: 1, lost: 1 },
        },
      });
    }
    const body = responses[path];
    return route.fulfill({
      status: body === undefined ? 404 : 200,
      json: body ?? { detail: "No synthetic fixture for this endpoint" },
    });
  });
  return requests;
}

// Inspect Chromium's actual accessibility tree, not just DOM attributes. These are
// the names and pressed states available for AT announcements, not recorded speech.
async function expectAnnouncementState(session: CDPSession, names: string[], active: string) {
  await expect
    .poll(async () => {
      const { nodes } = await session.send("Accessibility.getFullAXTree");
      return nodes
        .filter(
          (node) =>
            !node.ignored && node.role?.value === "button" && names.includes(node.name?.value),
        )
        .map((node) => ({
          name: node.name?.value,
          pressed: String(
            node.properties?.find((property) => property.name === "pressed")?.value.value,
          ),
        }));
    })
    .toEqual(names.map((name) => ({ name, pressed: String(name === active) })));
}

async function expectKeyboardFocus(button: Locator) {
  await expect(button).toBeFocused();
  await expect(button).toHaveCSS("--tw-ring-shadow", /3px/);
}

test("contact statuses keep keyboard focus, visible selection, and announced state in sync", async ({
  page,
}) => {
  const requests = await fixture(page);
  await page.goto("/contacts");
  const session = await page.context().newCDPSession(page);
  const group = page.getByRole("group", {
    name: /^Contact status: counts across all matching contacts/,
  });
  const buttons = group.getByRole("button");
  await expect(buttons).toHaveCount(6);
  await expectAnnouncementState(session, statusNames, "All 5");
  const selectedBackground = await buttons
    .first()
    .evaluate((button) => getComputedStyle(button).backgroundColor);
  await expect(buttons.nth(1)).not.toHaveCSS("background-color", selectedBackground);

  await buttons.first().focus();
  // Tab to every status; Enter and Space both activate native buttons.
  for (const [index, status] of statuses.entries()) {
    await page.keyboard.press("Tab");
    const button = buttons.nth(index + 1);
    await expectKeyboardFocus(button);
    await expect(button).toHaveAccessibleName(statusNames[index + 1]);
    await expect(button).toHaveAttribute("aria-pressed", "false");
    await page.keyboard.press(index % 2 === 0 ? "Enter" : "Space");
    await expect(button).toHaveAttribute("aria-pressed", "true");
    await expect(group.getByRole("button", { pressed: true })).toHaveCount(1);
    await expect(page.getByRole("table").getByRole("row")).toHaveCount(2);
    await expect(page.getByRole("table")).toContainText(`Synthetic ${status}`);
    await expectAnnouncementState(session, statusNames, statusNames[index + 1]);
    await expectKeyboardFocus(button);
    await expect(button).toHaveClass(/bg-background/);
    await expect(button).toHaveCSS("background-color", selectedBackground);
    await expect(buttons.first()).not.toHaveClass(/bg-background/);
    await expect(buttons.first()).not.toHaveCSS("background-color", selectedBackground);
    expect(
      requests.some((request) => request.path.endsWith("/contacts") && request.status === status),
    ).toBe(true);
    // Re-activating the active choice must not toggle it off.
    await page.keyboard.press(index % 2 === 0 ? "Space" : "Enter");
    await expect(button).toHaveAttribute("aria-pressed", "true");
  }

  for (let index = 0; index < statuses.length; index++) await page.keyboard.press("Shift+Tab");
  await expectKeyboardFocus(buttons.first());
  await page.keyboard.press("Space");
  await expect(page.getByRole("table").getByRole("row")).toHaveCount(6);
  await expectAnnouncementState(session, statusNames, "All 5");
  await expectKeyboardFocus(buttons.first());
  await expect(buttons.first()).toHaveCSS("background-color", selectedBackground);
  await page.screenshot({
    path: test.info().outputPath("contacts-selected-focus.png"),
    fullPage: true,
  });
  // Pointer activation still chooses the same single status.
  await buttons.nth(3).click();
  await expectAnnouncementState(session, statusNames, "Qualified 1");
  await expect(page.getByRole("table")).toContainText("Synthetic qualified");
  expect(requests.filter((request) => request.method !== "GET")).toEqual([]);
  await session.detach();
});

test("practice choices retain names, keyboard activation, and setup values across selection", async ({
  page,
}) => {
  const requests = await fixture(page);
  await page.goto("/agents/practice");
  const session = await page.context().newCDPSession(page);
  const group = page.getByRole("group", { name: "Who is practicing?", exact: true });
  await expect(group).toBeVisible();
  const ai = group.getByRole("button", { name: modeNames[0], exact: true });
  const human = group.getByRole("button", { name: modeNames[1], exact: true });
  await expectAnnouncementState(session, modeNames, modeNames[0]);
  const selectedBackground = await ai.evaluate(
    (button) => getComputedStyle(button).backgroundColor,
  );
  await expect(human).not.toHaveCSS("background-color", selectedBackground);
  await page.getByLabel("Agent", { exact: true }).click();
  await page.getByRole("option", { name: "Synthetic rep", exact: true }).click();
  await page.getByLabel("Prospect persona", { exact: true }).click();
  await page.getByRole("option", { name: "Synthetic prospect", exact: true }).click();
  await expect(page.getByLabel("Prospect persona", { exact: true })).toBeFocused();
  await page.keyboard.press("Tab");
  await expectKeyboardFocus(ai);
  await page.keyboard.press("Space");
  await expectAnnouncementState(session, modeNames, modeNames[0]);
  await page.keyboard.press("Tab");
  await expectKeyboardFocus(human);
  await expect(human).toHaveAccessibleName(modeNames[1]);
  await expect(human).toHaveAttribute("aria-pressed", "false");
  await page.keyboard.press("Space");
  await expectAnnouncementState(session, modeNames, modeNames[1]);
  await expectKeyboardFocus(human);
  await expect(human).toHaveAttribute("data-variant", "default");
  await expect(human).toHaveCSS("background-color", selectedBackground);
  await expect(ai).toHaveAttribute("data-variant", "outline");
  await expect(ai).not.toHaveCSS("background-color", selectedBackground);
  await expect(page.getByLabel("Conversation length", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Start practice", exact: true })).toBeEnabled();
  await page.screenshot({
    path: test.info().outputPath("human-selected-focus.png"),
    fullPage: true,
  });
  await page.keyboard.press("Enter");
  await expectAnnouncementState(session, modeNames, modeNames[1]);

  await page.keyboard.press("Shift+Tab");
  await expectKeyboardFocus(ai);
  await page.keyboard.press("Enter");
  await expectAnnouncementState(session, modeNames, modeNames[0]);
  await expectKeyboardFocus(ai);
  await expect(ai).toHaveAttribute("data-variant", "default");
  await expect(ai).toHaveCSS("background-color", selectedBackground);
  await expect(human).toHaveAttribute("data-variant", "outline");
  await expect(human).not.toHaveCSS("background-color", selectedBackground);
  await expect(page.getByLabel("Conversation length", { exact: true })).toContainText(
    "Standard (6 turns)",
  );
  await expect(page.getByLabel("Agent", { exact: true })).toContainText("Synthetic rep");
  await expect(page.getByLabel("Prospect persona", { exact: true })).toContainText(
    "Synthetic prospect",
  );
  await expect(page.getByRole("button", { name: "Run rehearsal", exact: true })).toBeEnabled();
  await human.click();
  await expectAnnouncementState(session, modeNames, modeNames[1]);
  await ai.click();
  await expectAnnouncementState(session, modeNames, modeNames[0]);
  // Merely changing the chooser must never start a paid rehearsal.
  expect(requests.filter((request) => request.method !== "GET")).toEqual([]);
  await session.detach();
});
