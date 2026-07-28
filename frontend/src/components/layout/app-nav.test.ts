import { describe, expect, it } from "vitest";

import type { Capability } from "@/lib/permissions";

import {
  canSeeNavItem,
  isFieldOperationalPath,
  setupNavItem,
  workspaceNavItems,
  toolsNavItems,
  type AppNavItem,
} from "./app-nav";

// A capability checker that grants everything — proves the field tier is gated
// by the operational allowlist, NOT by capabilities.
const canAll = (_capability: Capability) => true;
// Grants nothing.
const canNone = (_capability: Capability) => false;

function navItem(url: string, requires?: Capability): AppNavItem {
  return { title: url, url, icon: (() => null) as never, requires };
}

describe("isFieldOperationalPath", () => {
  it("allows the jobs schedule and calendar (and their sub-routes)", () => {
    expect(isFieldOperationalPath("/jobs")).toBe(true);
    expect(isFieldOperationalPath("/jobs/123")).toBe(true);
    expect(isFieldOperationalPath("/calendar")).toBe(true);
    expect(isFieldOperationalPath("/calendar/week")).toBe(true);
  });

  it("blocks every other CRM surface", () => {
    for (const path of ["/contacts", "/opportunities", "/campaigns", "/billing", "/", "/jobsy"]) {
      expect(isFieldOperationalPath(path)).toBe(false);
    }
  });
});

describe("canSeeNavItem — field technician is fail-closed to operational routes", () => {
  it("shows only jobs/calendar to field techs, even with all capabilities", () => {
    expect(canSeeNavItem(navItem("/jobs"), "field", canAll)).toBe(true);
    expect(canSeeNavItem(navItem("/calendar"), "field", canAll)).toBe(true);
    // Non-operational items are hidden regardless of capability grants.
    expect(canSeeNavItem(navItem("/contacts"), "field", canAll)).toBe(false);
    expect(canSeeNavItem(navItem("/campaigns"), "field", canAll)).toBe(false);
    expect(canSeeNavItem(navItem("/billing", "billing:read"), "field", canAll)).toBe(false);
  });

  it("a newly added CRM nav item does not leak to field techs by default", () => {
    // No `requires` set — would be visible to everyone under the old predicate.
    expect(canSeeNavItem(navItem("/brand-new-feature"), "field", canAll)).toBe(false);
  });

  it("non-field tiers keep the capability gate", () => {
    // tech/member tier: capability-driven.
    expect(canSeeNavItem(navItem("/contacts"), "tech", canAll)).toBe(true);
    expect(canSeeNavItem(navItem("/billing", "billing:read"), "tech", canNone)).toBe(false);
    expect(canSeeNavItem(navItem("/contacts"), "manager", canAll)).toBe(true);
  });
});

describe("real nav items under the field tier", () => {
  it("hides Contacts/Campaigns but shows Jobs & Calendar", () => {
    const contacts = workspaceNavItems.find((i) => i.url === "/contacts")!;
    const jobs = toolsNavItems.find((i) => i.url === "/jobs")!;
    const calendar = toolsNavItems.find((i) => i.url === "/calendar")!;
    expect(canSeeNavItem(contacts, "field", canAll)).toBe(false);
    expect(canSeeNavItem(jobs, "field", canAll)).toBe(true);
    expect(canSeeNavItem(calendar, "field", canAll)).toBe(true);
  });
});

describe("setupNavItem (first-run \"Finish setup\" entry)", () => {
  it("is gated on workspace:manage like the rest of the setup surface", () => {
    expect(setupNavItem.url).toBe("/onboarding");
    expect(setupNavItem.requires).toBe("workspace:manage");
  });

  it("is hidden from field techs even with all capabilities", () => {
    // Regression: the sidebar rendered this item outside `canSeeNavItem`, so a
    // technician saw "Finish setup" and could open the owner setup wizard.
    expect(canSeeNavItem(setupNavItem, "field", canAll)).toBe(false);
  });

  it("stays visible to owners/admins, and is hidden from tiers that cannot manage the workspace", () => {
    expect(canSeeNavItem(setupNavItem, "admin", canAll)).toBe(true);
    expect(canSeeNavItem(setupNavItem, "manager", canNone)).toBe(false);
    expect(canSeeNavItem(setupNavItem, "tech", canNone)).toBe(false);
  });
});

describe("Light Designer nav item (folded into the Quotes hub)", () => {
  const designer = workspaceNavItems.find((i) => i.title === "Light Designer");

  it("is a command-palette-only deep link into the Quotes designer tab", () => {
    expect(designer).toBeDefined();
    // Lives as a tab in the unified Quotes & Estimates hub, so it deep-links to
    // the tab rather than the retired standalone /estimator route.
    expect(designer!.url).toBe("/quotes?tab=designer");
    // Out of the sidebar (one quoting home), but still searchable + URL-reachable.
    expect(designer!.sidebar).toBe(false);
    expect(designer!.commandPalette).toBe(true);
    // Gated like the other quoting surfaces.
    expect(designer!.requires).toBe("billing:read");
  });

  it("stays fail-closed to field techs even with all capabilities", () => {
    expect(canSeeNavItem(designer!, "field", canAll)).toBe(false);
  });
});

describe("Christmas Lights seasonal hub nav item", () => {
  const christmas = workspaceNavItems.find(
    (i) => i.url === "/christmas-lights",
  );

  it("is registered with a festive accent and billing gate", () => {
    expect(christmas).toBeDefined();
    // Named for the seasonal estimator workflow it fronts.
    expect(christmas!.title).toBe("Christmas Light Estimator");
    // The seasonal tab must read as visually distinct (drives the tinted icon).
    expect(christmas!.accent).toBe("christmas");
    // Gated like the other quoting surfaces (Quotes/Estimator/Invoices).
    expect(christmas!.requires).toBe("billing:read");
    // Folded into the unified Quotes & Estimates hub: out of the sidebar, but
    // still reachable via the command palette (and by URL).
    expect(christmas!.sidebar).toBe(false);
    expect(christmas!.commandPalette).toBe(true);
  });

  it("follows the capability gate for non-field tiers", () => {
    expect(canSeeNavItem(christmas!, "manager", canAll)).toBe(true);
    expect(canSeeNavItem(christmas!, "tech", canNone)).toBe(false);
  });

  it("stays fail-closed to field techs even with all capabilities", () => {
    expect(canSeeNavItem(christmas!, "field", canAll)).toBe(false);
  });
});
