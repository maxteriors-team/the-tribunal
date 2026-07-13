import { describe, expect, it } from "vitest";

import type { Capability } from "@/lib/permissions";

import {
  canSeeNavItem,
  isFieldOperationalPath,
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
