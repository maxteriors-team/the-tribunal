import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import type { RehearsalRun } from "../src/types/roleplay";

// Real browser/UI and API client, synthetic durable API boundary. Never call providers.
const north = "11111111-1111-4111-8111-111111111111";
const south = "11111111-1111-4111-8111-222222222222";
const agentId = "22222222-2222-4222-8222-222222222222";
const personaId = "33333333-3333-4333-8333-333333333333";
const firstId = "44444444-4444-4444-8444-444444444444";
const secondId = "55555555-5555-4555-8555-555555555555";
const stamp = "2026-09-10T12:00:00Z";

function savedRun(overrides: Partial<RehearsalRun> = {}): RehearsalRun {
  return {
    id: firstId,
    workspace_id: north,
    agent_id: agentId,
    persona_id: personaId,
    agent_name: "Synthetic rep",
    persona_name: "Synthetic prospect",
    rehearsee: "ai",
    channel: "voice",
    status: "pending",
    pending_action: "agent",
    attempt_count: 1,
    retryable: false,
    overall_score: null,
    objection_coverage: null,
    tone_score: null,
    booking_attempted: null,
    max_turns: 6,
    transcript: [],
    scores: {},
    strengths: [],
    gaps: [],
    suggestions: [],
    summary: null,
    error: null,
    created_at: stamp,
    updated_at: stamp,
    completed_at: null,
    ...overrides,
  };
}

function runUrl(runId: string, workspaceId = north) {
  return `/agents/practice?workspace=${workspaceId}&runId=${runId}`;
}

async function fixture(page: Page, initial: RehearsalRun[] = []) {
  const state = {
    runs: new Map(initial.map((run) => [run.id, run])),
    requests: [] as { method: string; path: string; body: Record<string, unknown> | null }[],
    failHistory: false,
    failDetail: false,
    failChoices: false,
    loseCreateResponse: false,
    loseTurnResponse: false,
    loseRetryResponse: false,
    rejectRetry: false,
    detailGate: null as Promise<void> | null,
    errors: [] as string[],
  };
  const identities = new Map<string, string>();
  page.on("pageerror", (error) => state.errors.push(error.message));
  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    // All API requests are intercepted, including an externally configured API origin.
    // No non-local analytics, provider, or other external requests are allowed through.
    if (!url.pathname.startsWith("/api/")) {
      return ["localhost", "127.0.0.1"].includes(url.hostname)
        ? route.continue()
        : route.abort("blockedbyclient");
    }
    const path = url.pathname.replace(/\/$/, "");
    const method = request.method();
    const body: Record<string, unknown> | null = request.postData() ? request.postDataJSON() : null;
    state.requests.push({ method, path, body });
    const json = (data: unknown, status = 200) => route.fulfill({ status, json: data });
    const workspaces = [north, south].map((id) => ({
      workspace: {
        id,
        name: id === north ? "North practice" : "South practice",
        slug: id === north ? "north" : "south",
        settings: { timezone: "America/New_York" },
        onboarding_completed_at: stamp,
        is_active: true,
        created_at: stamp,
        updated_at: stamp,
      },
      role: "owner",
      is_default: id === north,
    }));
    if (method === "OPTIONS") return route.fulfill({ status: 204 });
    if (path === "/api/v1/auth/me")
      return json({
        id: 999999,
        email: "practice@example.invalid",
        full_name: "Synthetic operator",
        is_active: true,
        default_workspace_id: north,
        created_at: stamp,
      });
    if (path === "/api/v1/workspaces") return json(workspaces);
    const workspace = workspaces.find((entry) =>
      path.startsWith(`/api/v1/workspaces/${entry.workspace.id}`),
    );
    if (!workspace) return json({ detail: "Fixture endpoint unavailable" }, 404);
    const workspaceId = workspace.workspace.id;
    const suffix = path.slice(`/api/v1/workspaces/${workspaceId}`.length);
    if (!suffix) return json(workspace.workspace);
    if (suffix === "/agents")
      return state.failChoices
        ? json({ detail: "Choices offline" }, 503)
        : json({
            items: [
              {
                id: agentId,
                workspace_id: workspaceId,
                name: "Synthetic rep",
                is_active: true,
                channel: "both",
                capabilities: ["sms", "voice"],
                created_at: stamp,
                updated_at: stamp,
              },
            ],
            total: 1,
            page: 1,
            page_size: 50,
            pages: 1,
          });
    if (suffix === "/roleplay/personas")
      return state.failChoices
        ? json({ detail: "Choices offline" }, 503)
        : json([
            {
              id: personaId,
              workspace_id: workspaceId,
              name: "Synthetic prospect",
              difficulty: "medium",
              objections: [],
              is_builtin: true,
              created_at: stamp,
              updated_at: stamp,
            },
          ]);
    if (suffix === "/roleplay/runs") {
      if (method === "GET") {
        if (state.failHistory) return json({ detail: "History offline" }, 503);
        return json(
          [...state.runs.values()]
            .filter((run) => run.workspace_id === workspaceId)
            .reverse()
            .map((run) => {
              const summary: Partial<RehearsalRun> = { ...run };
              delete summary.transcript;
              return summary;
            }),
        );
      }
      if (method === "POST") {
        const identity = `${workspaceId}:${body?.idempotency_key}`;
        const existingId = identities.get(identity);
        if (existingId) return json(state.runs.get(existingId), 202);
        const run = savedRun({
          workspace_id: workspaceId,
          rehearsee: String(body?.rehearsee),
          channel: String(body?.channel ?? "sms"),
          max_turns: Number(body?.max_turns ?? 6),
          attempt_count: 0,
          pending_action: body?.rehearsee === "human" ? "start" : "agent",
        });
        identities.set(identity, run.id);
        state.runs.set(run.id, run);
        if (state.loseCreateResponse) {
          state.loseCreateResponse = false;
          return route.abort("timedout");
        }
        return json(run, 202);
      }
    }
    const match = suffix.match(/^\/roleplay\/runs\/([^/]+)(?:\/(turn|score|retry))?$/);
    if (match) {
      const run = state.runs.get(match[1]);
      if (!run || run.workspace_id !== workspaceId) return json({ detail: "Run not found" }, 404);
      const action = match[2];
      if (method === "GET" && !action) {
        if (state.failDetail) return json({ detail: "Status offline" }, 503);
        const snapshot = structuredClone(run);
        const gate = state.detailGate;
        state.detailGate = null;
        if (gate) await gate;
        return json(snapshot);
      }
      if (method === "POST" && action === "turn") {
        expect(body?.expected_turn_count).toBe(run.transcript.length);
        const updated = {
          ...run,
          status: "pending",
          pending_action: "prospect",
          transcript: [
            ...run.transcript,
            { role: "agent" as const, content: String(body?.message) },
          ],
        };
        state.runs.set(run.id, updated);
        if (state.loseTurnResponse) {
          state.loseTurnResponse = false;
          return route.abort("timedout");
        }
        return json(updated, 202);
      }
      if (method === "POST" && action === "retry") {
        expect(body?.expected_attempt_count).toBe(run.attempt_count);
        if (state.rejectRetry) return json({ detail: "Retry temporarily unavailable" }, 503);
        const updated = { ...run, status: "pending", retryable: false, error: null };
        state.runs.set(run.id, updated);
        if (state.loseRetryResponse) {
          state.loseRetryResponse = false;
          return route.abort("timedout");
        }
        return json(updated, 202);
      }
      if (method === "POST" && action === "score") {
        const updated = { ...run, status: "pending", pending_action: "score" };
        state.runs.set(run.id, updated);
        return json(updated, 202);
      }
    }
    if (/^\/conversations\/unread/.test(suffix))
      return json({ unread_conversations: 0, unread_messages: 0 });
    if (suffix === "/nudges/stats")
      return json({ pending: 0, snoozed: 0, completed: 0, dismissed: 0 });
    if (suffix === "/pending-actions/stats")
      return json({ pending: 0, approved: 0, rejected: 0, expired: 0, total: 0 });
    if (/\/(unread-count|count)$/.test(suffix)) return json({ count: 0 });
    return json({ detail: `No synthetic fixture for ${suffix}` }, 501);
  });
  return state;
}

async function chooseSetup(page: Page, human = false) {
  await page.goto("/agents/practice");
  await page.getByLabel("Agent", { exact: true }).click();
  await page.getByRole("option", { name: "Synthetic rep", exact: true }).click();
  await page.getByLabel("Prospect persona", { exact: true }).click();
  await page.getByRole("option", { name: "Synthetic prospect", exact: true }).click();
  if (human) await page.getByRole("button", { name: "Me (human rep)" }).click();
}

function writes(state: Awaited<ReturnType<typeof fixture>>, action?: string) {
  return state.requests.filter(
    (request) =>
      request.method === "POST" &&
      request.path.endsWith(`/roleplay/runs${action ? `/${firstId}/${action}` : ""}`),
  );
}

const selected = (page: Page) => page.getByRole("region", { name: "Selected rehearsal" });

test("human dialogue survives a lost turn response, refresh, navigation, and scoring", async ({
  page,
}, info) => {
  const state = await fixture(page);
  await chooseSetup(page, true);
  await page.getByRole("button", { name: "Start practice", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`runId=${firstId}`));
  state.runs.set(
    firstId,
    savedRun({
      rehearsee: "human",
      status: "running",
      pending_action: null,
      transcript: [{ role: "prospect", content: "Can you explain the estimate?" }],
    }),
  );
  await page.getByRole("button", { name: "Refresh status" }).click();
  await expect(
    selected(page).getByText("Can you explain the estimate?", { exact: true }),
  ).toBeVisible();
  state.loseTurnResponse = true;
  await page
    .getByRole("textbox", { name: "Your reply" })
    .fill("Your estimate includes installation.");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(
    selected(page).getByText("Your estimate includes installation.", { exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Your reply" })).toHaveValue("");
  await page.reload();
  await expect(
    selected(page).getByText("Your estimate includes installation.", { exact: true }),
  ).toBeVisible();
  const pending = state.runs.get(firstId)!;
  state.runs.set(firstId, {
    ...pending,
    status: "running",
    pending_action: null,
    transcript: [...pending.transcript, { role: "prospect", content: "That helps, thank you." }],
  });
  await page.getByRole("button", { name: "Refresh status" }).click();
  await expect(page.getByRole("button", { name: /Finish.*score/ })).toBeEnabled();
  await expect(
    page.getByRole("list", { name: "Saved rehearsals" }).getByRole("link"),
  ).toContainText("Ready to resume");
  await page.screenshot({ path: info.outputPath("human-desktop.png"), fullPage: true });
  await page.getByRole("link", { name: "New rehearsal" }).click();
  await expect(page.getByText("Set up a rehearsal", { exact: true })).toBeVisible();
  const historyLink = page.getByRole("list", { name: "Saved rehearsals" }).getByRole("link");
  await historyLink.focus();
  await page.keyboard.press("Enter");
  await expect(selected(page).getByText("That helps, thank you.", { exact: true })).toBeVisible();
  await page.goBack();
  await expect(page.getByText("Set up a rehearsal", { exact: true })).toBeVisible();
  await page.goForward();
  await expect(
    selected(page).getByText("Your estimate includes installation.", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: /Finish.*score/ }).click();
  await expect(selected(page).getByText("Scoring rehearsal…", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Send", exact: true })).toBeDisabled();
  await page.reload();
  await expect(
    selected(page).getByText("Your estimate includes installation.", { exact: true }),
  ).toBeVisible();
  expect(writes(state)).toHaveLength(1);
  expect(writes(state, "turn")).toHaveLength(1);
  expect(writes(state, "score")).toHaveLength(1);
  expect(writes(state)[0].body?.idempotency_key).toMatch(/^[0-9a-f-]{36}$/);
  expect(state.errors).toEqual([]);
});

test("history selection is URL-bound instead of silently showing the latest run", async ({
  page,
}) => {
  const state = await fixture(page, [
    savedRun({
      status: "completed",
      pending_action: null,
      overall_score: 0,
      summary: "A genuine zero score",
      transcript: [{ role: "agent", content: "Older saved dialogue" }],
    }),
    savedRun({ id: secondId, persona_name: "Newest prospect" }),
  ]);
  await page.goto("/agents/practice");
  const older = page
    .getByRole("list", { name: "Saved rehearsals" })
    .getByRole("link", { name: /Synthetic prospect/ });
  await older.click();
  await expect(page).toHaveURL(new RegExp(`runId=${firstId}`));
  await expect(older).toHaveAttribute("aria-current", "page");
  await expect(selected(page).getByText("A genuine zero score")).toBeVisible();
  await expect(selected(page).getByText("Overall score", { exact: true })).toBeVisible();
  state.failChoices = true; // Historical reports do not depend on setup dropdowns.
  await page.reload();
  await expect(selected(page).getByText("Older saved dialogue", { exact: true })).toBeVisible();
  await expect(selected(page).getByText("0", { exact: true })).toBeVisible();
  expect(writes(state)).toHaveLength(0);
  expect(state.errors).toEqual([]);
});

test("a timed-out AI creation is recovered through history without another paid start", async ({
  page,
}) => {
  const state = await fixture(page);
  state.loseCreateResponse = true;
  await chooseSetup(page);
  await page.getByRole("button", { name: "Run rehearsal", exact: true }).click();
  await expect(page.getByText(/Couldn't confirm the request/)).toBeVisible();
  await page.getByRole("list", { name: "Saved rehearsals" }).getByRole("link").click();
  await expect(selected(page).getByText("Rehearsal in progress…", { exact: true })).toBeVisible();
  await page.reload();
  await expect(selected(page).getByText("Rehearsal in progress…", { exact: true })).toBeVisible();
  await expect(selected(page).getByText("Overall score", { exact: true })).toHaveCount(0);
  state.runs.set(
    firstId,
    savedRun({
      status: "completed",
      pending_action: null,
      overall_score: 84,
      summary: "Recovered AI report",
      transcript: [{ role: "agent", content: "Saved AI pitch" }],
    }),
  );
  await page.getByRole("button", { name: "Refresh status" }).click();
  await expect(selected(page).getByText("Recovered AI report")).toBeVisible();
  await page.reload();
  await expect(selected(page).getByText("Saved AI pitch", { exact: true })).toBeVisible();
  expect(writes(state)).toHaveLength(1);
  expect(writes(state, "retry")).toHaveLength(0);
  expect(state.errors).toEqual([]);
});

test("read failures retry GET only and keep the selected transcript accessible", async ({
  page,
}) => {
  const state = await fixture(page, [
    savedRun({
      rehearsee: "human",
      status: "running",
      pending_action: null,
      transcript: [{ role: "agent", content: "Keep this saved reply" }],
    }),
  ]);
  state.failDetail = true;
  state.failHistory = true;
  await page.goto(runUrl(firstId));
  await expect(selected(page).getByText(/Couldn't load the latest saved run/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Retry history" })).toBeVisible();
  state.failDetail = false;
  await page.getByRole("button", { name: "Refresh status" }).click();
  await expect(selected(page).getByText("Keep this saved reply", { exact: true })).toBeVisible();
  state.failDetail = true;
  await page.getByRole("button", { name: "Refresh status" }).click();
  await expect(selected(page).getByText(/Showing the last saved transcript/)).toBeVisible();
  await expect(selected(page).getByText("Keep this saved reply", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: /Finish.*score/ })).toBeDisabled();
  state.failHistory = false;
  await page.getByRole("button", { name: "Retry history" }).click();
  await expect(page.getByRole("list", { name: "Saved rehearsals" }).getByRole("link")).toHaveCount(
    1,
  );
  state.failDetail = false;
  await page.getByRole("button", { name: "Refresh status" }).click();
  await expect(page.getByRole("button", { name: /Finish.*score/ })).toBeEnabled();
  expect(writes(state)).toHaveLength(0);
  expect(writes(state, "retry")).toHaveLength(0);
  expect(state.errors).toEqual([]);
});

test("workspace switches discard selection, drafts, and late responses from the previous workspace", async ({
  page,
}) => {
  const state = await fixture(page, [
    savedRun({
      rehearsee: "human",
      status: "running",
      pending_action: null,
      transcript: [{ role: "prospect", content: "North-only dialogue" }],
    }),
    savedRun({
      id: secondId,
      workspace_id: south,
      persona_name: "Southern prospect",
      status: "completed",
      pending_action: null,
      summary: null,
      transcript: [{ role: "prospect", content: "South-only dialogue" }],
    }),
  ]);
  await page.goto(runUrl(firstId));
  await expect(selected(page).getByText("North-only dialogue", { exact: true })).toBeVisible();
  await page.getByRole("textbox", { name: "Your reply" }).fill("North-only unsent draft");
  let release = () => {};
  state.detailGate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const pendingRead = page.waitForRequest((request) =>
    request.url().includes(`/roleplay/runs/${firstId}`),
  );
  await page.getByRole("button", { name: "Refresh status" }).click();
  await pendingRead;
  await page.getByRole("button", { name: /North practice/ }).click();
  await page.getByRole("menuitem", { name: "South practice", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`workspace=${south}$`));
  release();
  await expect(page.getByText("North-only dialogue", { exact: true })).toHaveCount(0);
  await page
    .getByRole("list", { name: "Saved rehearsals" })
    .getByRole("link", { name: /Southern prospect/ })
    .click();
  await expect(selected(page).getByText("South-only dialogue", { exact: true })).toBeVisible();
  await page.reload();
  await expect(selected(page).getByText("South-only dialogue", { exact: true })).toBeVisible();
  expect(
    state.requests.some(
      (request) => request.path === `/api/v1/workspaces/${south}/roleplay/runs/${firstId}`,
    ),
  ).toBe(false);
  expect(writes(state)).toHaveLength(0);
  expect(state.errors).toEqual([]);
});

test("failed-step retries use the observed attempt and recover a lost retry response", async ({
  page,
}) => {
  const state = await fixture(page, [
    savedRun({
      status: "failed",
      pending_action: "score",
      retryable: true,
      attempt_count: 3,
      error: "Synthetic scorer output was invalid",
      transcript: [{ role: "agent", content: "Do not regenerate this dialogue" }],
    }),
  ]);
  await page.goto(runUrl(firstId));
  await expect(
    selected(page).getByText("Rehearsal failed — unscored", { exact: true }),
  ).toBeVisible();
  await expect(selected(page).getByText("Overall score", { exact: true })).toHaveCount(0);
  state.rejectRetry = true;
  await page.getByRole("button", { name: "Retry failed step" }).click();
  await expect(selected(page).getByText(/Retry temporarily unavailable/)).toBeVisible();
  state.rejectRetry = false;
  state.loseRetryResponse = true;
  await page.getByRole("button", { name: "Retry failed step" }).click();
  await expect(selected(page).getByText("Scoring rehearsal…", { exact: true })).toBeVisible();
  await page.reload();
  await expect(
    selected(page).getByText("Do not regenerate this dialogue", { exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Retry failed step" })).toHaveCount(0);
  expect(writes(state)).toHaveLength(0);
  expect(writes(state, "retry").map((request) => request.body)).toEqual([
    { expected_attempt_count: 3 },
    { expected_attempt_count: 3 },
  ]);
  expect(state.runs.get(firstId)?.attempt_count).toBe(3); // Only a worker claim increments it.
  expect(state.errors).toEqual([]);
});

test("explicit creation retry after reload reuses the unresolved identity", async ({ page }) => {
  const state = await fixture(page);
  state.loseCreateResponse = true;
  await chooseSetup(page);
  await page.getByRole("button", { name: "Run rehearsal", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Check history" })).toBeVisible();
  await chooseSetup(page); // Full navigation remounts the app, preserving only browser storage.
  await page.getByRole("button", { name: "Run rehearsal", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`runId=${firstId}`));
  const attempts = writes(state);
  expect(attempts).toHaveLength(2);
  expect(attempts[0].body?.idempotency_key).toBe(attempts[1].body?.idempotency_key);
  expect(state.runs.size).toBe(1);
  expect(state.errors).toEqual([]);
});

test("foreign and malformed links cannot reveal a different workspace's run", async ({ page }) => {
  const state = await fixture(page, [
    savedRun({
      workspace_id: south,
      transcript: [{ role: "agent", content: "Private south dialogue" }],
    }),
  ]);
  await page.goto(runUrl(firstId, north));
  await expect(selected(page).getByText("Rehearsal unavailable", { exact: true })).toBeVisible();
  await expect(page.getByText("Private south dialogue", { exact: true })).toHaveCount(0);
  const reads = state.requests.filter((request) => request.path.endsWith(`/runs/${firstId}`));
  expect(reads.length).toBeGreaterThan(0);
  expect(reads.every((request) => request.path.includes(`/workspaces/${north}/`))).toBe(true);
  const requestsBefore = state.requests.length;
  await page.goto(runUrl(encodeURIComponent("invalid/run")));
  await expect(
    page.getByText("This rehearsal link is invalid. Select a saved run from history."),
  ).toBeVisible();
  expect(
    state.requests.slice(requestsBefore).some((request) => request.path.includes("/runs/")),
  ).toBe(false);
  expect(writes(state)).toHaveLength(0);
  expect(state.errors).toEqual([]);
});

test("completed but unscored runs retain dialogue and clearly label text-only voice practice", async ({
  page,
}, info) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const state = await fixture(page, [
    savedRun({
      status: "completed",
      pending_action: null,
      overall_score: null,
      persona_name: `Synthetic ${"prospect".repeat(8)}`,
      transcript: [{ role: "prospect", content: `Saved unscored dialogue ${"long".repeat(60)}` }],
    }),
  ]);
  await page.goto(runUrl(firstId));
  await expect(selected(page).getByText("Completed · Unscored", { exact: true })).toBeVisible();
  await expect(selected(page).getByText(/Text-only · VOICE script/)).toBeVisible();
  await expect(selected(page).getByText(/Saved unscored dialogue/)).toBeVisible();
  await expect(selected(page).getByText("Overall score", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Retry failed step" })).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  for (const width of [320, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
    expect(
      await page
        .getByRole("region", { name: "Practice Arena", exact: true })
        .evaluate((element) => element.scrollWidth <= element.clientWidth),
    ).toBe(true);
    const accessibility = await new AxeBuilder({ page })
      .include('[aria-labelledby="practice-arena-heading"]')
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
      .analyze();
    expect(accessibility.violations).toEqual([]);
    await info.attach(`practice-accessibility-${width}`, {
      body: JSON.stringify(accessibility),
      contentType: "application/json",
    });
    await page.screenshot({ path: info.outputPath(`unscored-${width}.png`), fullPage: true });
  }
  expect(writes(state)).toHaveLength(0);
  expect(state.errors).toEqual([]);
});
