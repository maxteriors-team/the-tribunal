import { describe, expect, it } from "vitest";

import type { Capability } from "@/lib/permissions";

import {
  allNavItems,
  appNavSections,
  canSeeNavItem,
  findNavSectionIdForPath,
  isFieldOperationalPath,
  setupNavItem,
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

describe("sidebar sections fit the viewport", () => {
  // The sidebar keeps one section open, so its resting height is
  // `(sections - 1) x ~40px header + the open section`. Six 32px rows plus
  // eight other headers lands around 530px, which clears the ~570px of usable
  // nav height on a 1440x700 window. A seventh row starts pushing items back
  // off-screen, which is the regression this whole structure exists to prevent.
  const MAX_ITEMS_PER_SECTION = 6;

  it("keeps every section small enough to render without scrolling", () => {
    for (const section of appNavSections) {
      const sidebarItems = section.items.filter((item) => item.sidebar);
      expect(
        sidebarItems.length,
        `section "${section.title}" has ${sidebarItems.length} sidebar items`,
      ).toBeLessThanOrEqual(MAX_ITEMS_PER_SECTION);
    }
  });

  it("gives every section a unique id for the open/closed state", () => {
    const ids = appNavSections.map((section) => section.id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(ids.every((id) => id.length > 0)).toBe(true);
  });

  it("registers every nav item exactly once", () => {
    const urls = allNavItems.map((item) => item.url);
    expect(new Set(urls).size).toBe(urls.length);
  });
});

describe("findNavSectionIdForPath", () => {
  it("opens the section that owns the current route", () => {
    expect(findNavSectionIdForPath("/contacts")).toBe("customers");
    expect(findNavSectionIdForPath("/invoices")).toBe("sales");
    expect(findNavSectionIdForPath("/settings")).toBe("account");
  });

  it("matches sub-routes, so a contact detail page keeps Customers open", () => {
    expect(findNavSectionIdForPath("/contacts/6980/details")).toBe("customers");
    expect(findNavSectionIdForPath("/jobs/123")).toBe("operations");
  });

  it("prefers the longest matching url over a shorter prefix", () => {
    // Both /reports and /reports/sales are registered; the deeper route wins.
    expect(findNavSectionIdForPath("/reports/sales")).toBe("insights");
    // /find-leads/ad-library must not resolve via the /find-leads prefix alone.
    expect(findNavSectionIdForPath("/find-leads/ad-library")).toBe(
      "lead-discovery",
    );
  });

  it("ignores the query string on deep-linked items", () => {
    // Registered as `/quotes?tab=designer`; usePathname() never carries a query.
    expect(findNavSectionIdForPath("/quotes")).toBe("sales");
  });

  it("returns null for routes outside the nav", () => {
    expect(findNavSectionIdForPath("/onboarding")).toBeNull();
    expect(findNavSectionIdForPath("/nope")).toBeNull();
  });
});

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

describe("canSeeNavItem — the crew lead is fail-closed too", () => {
  // Regression guard. `lead` used to fall through to the capability branch,
  // and most nav items carry no `requires` at all — so a crew lead saw the
  // whole CRM sidebar (Contacts, Campaigns, Calls, Settings...) and clicked
  // into pages the API then refused.
  it("hides ungated CRM items from a lead technician", () => {
    for (const path of ["/contacts", "/campaigns", "/calls", "/settings", "/today"]) {
      expect(canSeeNavItem(navItem(path), "lead", canAll)).toBe(false);
    }
  });

  it("shows the lead exactly the on-site surface", () => {
    expect(canSeeNavItem(navItem("/jobs"), "lead", canAll)).toBe(true);
    expect(canSeeNavItem(navItem("/calendar"), "lead", canAll)).toBe(true);
  });

  it("a newly added CRM nav item does not leak to leads either", () => {
    expect(canSeeNavItem(navItem("/brand-new-feature"), "lead", canAll)).toBe(false);
  });
});

describe("real nav items under the on-site tiers", () => {
  const contacts = allNavItems.find((i) => i.url === "/contacts")!;
  const jobs = allNavItems.find((i) => i.url === "/jobs")!;
  const calendar = allNavItems.find((i) => i.url === "/calendar")!;
  const upsell = allNavItems.find((i) => i.url === "/upsell")!;

  it("hides Contacts/Campaigns but shows Jobs & Calendar", () => {
    expect(canSeeNavItem(contacts, "field", canAll)).toBe(false);
    expect(canSeeNavItem(jobs, "field", canAll)).toBe(true);
    expect(canSeeNavItem(calendar, "field", canAll)).toBe(true);
  });

  it("shows 'Sell add-on' to a crew lead and hides it from a plain technician", () => {
    // The allowlist alone is not enough here: /upsell is operational for both
    // tiers, so the capability gate is what separates them.
    const canSell = (c: string) => c === "upsell:sell" || c === "jobs:read";
    const jobsOnly = (c: string) => c === "jobs:read";
    expect(canSeeNavItem(upsell, "lead", canSell as typeof canAll)).toBe(true);
    expect(canSeeNavItem(upsell, "field", jobsOnly as typeof canAll)).toBe(false);
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
  const designer = allNavItems.find((i) => i.title === "Light Designer");

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

describe("Segments nav item (folded into the campaign builder)", () => {
  const segments = allNavItems.find((i) => i.url === "/segments");

  it("is a command-palette-only entry, not a duplicate sidebar row", () => {
    expect(segments).toBeDefined();
    expect(segments!.title).toBe("Segments");
    // Recipient selection already lives inline in the campaign builder and on
    // Contacts via "Save as Segment", so a sidebar row is a second front door.
    expect(segments!.sidebar).toBe(false);
    // Still searchable and URL-reachable: saved segments are what the AI growth
    // workflow, prebooking audiences, and the outbound auto-draft worker read,
    // so the management screen has to stay reachable.
    expect(segments!.commandPalette).toBe(true);
  });
});

describe("Christmas Lights seasonal hub nav item", () => {
  const christmas = allNavItems.find((i) => i.url === "/christmas-lights");

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
