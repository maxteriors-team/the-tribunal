import type { BrowserContext, Page, TestInfo } from "@playwright/test";
import { expect } from "@playwright/test";

interface TestUser {
  email: string;
  password: string;
}

type StorageState = Awaited<ReturnType<BrowserContext["storageState"]>>;

/** Credentials reserved for the one explicit seeded-login smoke test. */
export const TEST_USER: TestUser = {
  email: process.env.E2E_USER_EMAIL ?? "",
  password: process.env.E2E_USER_PASSWORD ?? "",
};

const workerStorageStates = new Map<number, StorageState>();
const workerUsers = new Map<number, TestUser>();

export function hasTestUser(): boolean {
  return TEST_USER.email.length > 0 && TEST_USER.password.length > 0;
}

export function canProvisionUsers(): boolean {
  return process.env.E2E_ALLOW_PROVISIONING === "1";
}

/**
 * Parallel authenticated specs require a different backend user per Playwright
 * worker. `E2E_USER_EMAIL_TEMPLATE` must contain `{worker}` (for example,
 * `playwright-{worker}@example.com`) unless opt-in provisioning is enabled.
 */
export function hasParallelTestUser(): boolean {
  const template = process.env.E2E_USER_EMAIL_TEMPLATE ?? "";
  return (
    canProvisionUsers() || (template.includes("{worker}") && Boolean(process.env.E2E_USER_PASSWORD))
  );
}

function configuredWorkerUser(parallelIndex: number): TestUser | null {
  const emailTemplate = process.env.E2E_USER_EMAIL_TEMPLATE;
  const password = process.env.E2E_USER_PASSWORD;
  if (!emailTemplate?.includes("{worker}") || !password) return null;

  return {
    email: emailTemplate.replaceAll("{worker}", String(parallelIndex)),
    password,
  };
}

function provisionedWorkerUser(parallelIndex: number): TestUser {
  const cached = workerUsers.get(parallelIndex);
  if (cached) return cached;

  const runId = (process.env.E2E_RUN_ID ?? `${process.pid}-${Date.now()}`)
    .replace(/[^a-zA-Z0-9]/g, "")
    .slice(0, 24);
  const user = {
    email: `e2e-pw-${runId}-w${parallelIndex}@example.com`,
    password: process.env.E2E_PROVISION_PASSWORD ?? "Tribunal-E2E-Worker-2026!",
  };
  workerUsers.set(parallelIndex, user);
  return user;
}

async function restoreStorageState(page: Page, state: StorageState): Promise<void> {
  await page.context().addCookies(state.cookies);
  await page.addInitScript((origins) => {
    const originState = origins.find((entry) => entry.origin === window.location.origin);
    for (const { name, value } of originState?.localStorage ?? []) {
      window.localStorage.setItem(name, value);
    }
  }, state.origins);
}

async function submitLogin(page: Page, user: TestUser): Promise<void> {
  await page.goto("/login");
  // The login card title ("Welcome back") is a styled div rather than a heading.
  await expect(page.getByText(/welcome back/i)).toBeVisible();
  await page.getByLabel(/email/i).fill(user.email);
  await page.getByLabel(/password/i).fill(user.password);
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page).not.toHaveURL(/\/login(?:\?|$)/, { timeout: 15_000 });
}

async function provisionWorker(page: Page, user: TestUser): Promise<void> {
  await page.goto("/register");
  await expect(page.getByText(/create your account/i)).toBeVisible();
  await page.getByLabel(/full name/i).fill(`Playwright ${user.email.split("@")[0]}`);
  await page.getByLabel(/email/i).fill(user.email);
  await page.getByLabel(/password/i).fill(user.password);
  await page.getByRole("button", { name: /create account/i }).click();
  await expect(page).not.toHaveURL(/\/register(?:\?|$)/, { timeout: 20_000 });

  // Trigger SetupGate from a protected route before skipping. Going straight
  // to /onboarding can leave its cached setup status stale and redirect the
  // test back into onboarding after its next navigation.
  await page.goto("/contacts");
  await page.waitForURL(/\/onboarding(?:\?|$)/, { timeout: 10_000 }).catch(() => undefined);
  if (/\/onboarding(?:\?|$)/.test(new URL(page.url()).pathname)) {
    const skipOnboarding = page.getByRole("button", { name: "Skip for now" });
    await expect(skipOnboarding).toBeVisible({ timeout: 10_000 });
    await skipOnboarding.click();
    await expect(page).not.toHaveURL(/\/onboarding(?:\?|$)/, { timeout: 15_000 });
  }
}

/**
 * Authenticate with one session per Playwright worker. A worker logs in (or
 * provisions) once, then restores that worker's cookies in its later test
 * contexts. Different workers never rotate the same refresh token.
 *
 * Omitting `testInfo` is intentionally reserved for the seeded-login smoke test.
 */
export async function loginViaUI(page: Page, testInfo?: TestInfo): Promise<void> {
  if (!testInfo) {
    if (!hasTestUser()) {
      throw new Error("loginViaUI called without E2E_USER_EMAIL / E2E_USER_PASSWORD set");
    }
    await submitLogin(page, TEST_USER);
    return;
  }

  const parallelIndex = testInfo.parallelIndex;
  const cachedState = workerStorageStates.get(parallelIndex);
  if (cachedState) {
    await restoreStorageState(page, cachedState);
    await page.goto("/");
    await expect(page).not.toHaveURL(/\/login(?:\?|$)/);
    return;
  }

  const configuredUser = configuredWorkerUser(parallelIndex);
  const user = configuredUser ?? provisionedWorkerUser(parallelIndex);
  if (configuredUser) {
    await submitLogin(page, user);
  } else if (canProvisionUsers()) {
    await provisionWorker(page, user);
  } else {
    throw new Error(
      "Parallel auth requires E2E_ALLOW_PROVISIONING=1 or an " +
        "E2E_USER_EMAIL_TEMPLATE containing {worker}.",
    );
  }

  workerStorageStates.set(parallelIndex, await page.context().storageState());
}

/** Generate a unique suffix so reruns do not collide on unique constraints. */
export function uniqueSuffix(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
}
