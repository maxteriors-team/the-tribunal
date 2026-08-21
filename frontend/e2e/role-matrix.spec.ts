import { expect, test, type Page } from "@playwright/test";

const WORKSPACE_ID = "7f90e8ee-fb76-4cf9-9b3e-f81157c9b425";

type WorkspaceRole =
  | "owner"
  | "admin"
  | "manager"
  | "dispatcher"
  | "sales_rep"
  | "member"
  | "lead_technician"
  | "technician";

interface RoleRouteCase {
  role: WorkspaceRole;
  allowedPath: string;
  deniedPath?: string;
  deniedFallback?: "/contacts" | "/calendar";
}

const ROLE_ROUTE_CASES: readonly RoleRouteCase[] = [
  { role: "owner", allowedPath: "/phone-numbers" },
  { role: "admin", allowedPath: "/phone-numbers" },
  {
    role: "manager",
    allowedPath: "/campaigns/sms/new",
    deniedPath: "/phone-numbers",
    deniedFallback: "/contacts",
  },
  {
    role: "dispatcher",
    allowedPath: "/campaigns/sms/new",
    deniedPath: "/phone-numbers",
    deniedFallback: "/contacts",
  },
  {
    role: "sales_rep",
    allowedPath: "/campaigns/sms/new",
    deniedPath: "/phone-numbers",
    deniedFallback: "/contacts",
  },
  {
    role: "member",
    allowedPath: "/contacts",
    deniedPath: "/campaigns/sms/new",
    deniedFallback: "/contacts",
  },
  {
    role: "lead_technician",
    allowedPath: "/upsell",
    deniedPath: "/campaigns/sms/new",
    deniedFallback: "/calendar",
  },
  {
    role: "technician",
    allowedPath: "/calendar",
    deniedPath: "/upsell",
    deniedFallback: "/calendar",
  },
] as const;

const json = (body: unknown, status = 200) => ({
  status,
  contentType: "application/json",
  body: JSON.stringify(body),
});

async function installRoleSession(page: Page, role: WorkspaceRole): Promise<void> {
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;

    if (request.method() === "GET" && pathname === "/api/v1/auth/me") {
      await route.fulfill(
        json({
          id: 81,
          email: `${role}@example.com`,
          full_name: role,
          is_active: true,
          created_at: "2026-01-01T00:00:00Z",
          default_workspace_id: WORKSPACE_ID,
        }),
      );
      return;
    }

    if (request.method() === "GET" && pathname === "/api/v1/workspaces") {
      await route.fulfill(
        json([
          {
            workspace: {
              id: WORKSPACE_ID,
              name: "Role Matrix Workspace",
              slug: "role-matrix",
              description: null,
              settings: {},
              is_active: true,
              onboarding_completed_at: "2026-01-01T00:00:00Z",
              created_at: "2026-01-01T00:00:00Z",
              updated_at: "2026-01-01T00:00:00Z",
            },
            role,
            is_default: true,
          },
        ]),
      );
      return;
    }

    // Route access is the behavior under test. Page-specific queries may fail
    // closed without obscuring whether AppShell kept or redirected the route.
    await route.fulfill(json({ detail: `Not mocked: ${request.method()} ${pathname}` }, 404));
  });
}

for (const roleCase of ROLE_ROUTE_CASES) {
  test(`${roleCase.role} receives the correct protected route tier`, async ({ page }) => {
    test.setTimeout(60_000);
    await installRoleSession(page, roleCase.role);

    await page.goto(roleCase.allowedPath);
    await expect(page).toHaveURL(new RegExp(`${roleCase.allowedPath}$`));
    await expect(page.locator("[data-app-shell]")).toBeVisible({ timeout: 15_000 });

    if (!roleCase.deniedPath || !roleCase.deniedFallback) return;

    await page.goto(roleCase.deniedPath);
    await expect(page).toHaveURL(new RegExp(`${roleCase.deniedFallback}$`), {
      timeout: 20_000,
    });
  });
}
