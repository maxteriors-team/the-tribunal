import { describe, expect, it } from "vitest";

import { can, roleTier, type Capability } from "@/lib/permissions";

import {
  allNavItems,
  appNavSections,
  canAccessAppPath,
  canSeeNavItem,
  directManagementCapabilityForPath,
  findNavItemForPath,
  findNavSectionIdForPath,
  isFieldOperationalPath,
  setupNavItem,
  type AppNavItem,
} from "./app-nav";

// A capability checker that grants everything — proves the field tier is gated
// by the operational allowlist, NOT by capabilities.
const canAll: (capability: Capability) => boolean = () => true;
// Grants nothing.
const canNone: (capability: Capability) => boolean = () => false;

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
    expect(findNavSectionIdForPath("/calendar/week")).toBe("operations");
  });

  it("prefers the longest matching url over a shorter prefix", () => {
    // Both /reports and /reports/sales are registered; the deeper route wins.
    expect(findNavSectionIdForPath("/reports/sales")).toBe("insights");
    // /find-leads/ad-library must not resolve via the /find-leads prefix alone.
    expect(findNavSectionIdForPath("/find-leads/ad-library")).toBe("lead-discovery");
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
  it("allows the calendar and its sub-routes", () => {
    expect(isFieldOperationalPath("/calendar")).toBe(true);
    expect(isFieldOperationalPath("/calendar/week")).toBe(true);
  });

  it("still allows /jobs so an existing deep link can reach its redirect", () => {
    // `/jobs` has no screen any more, but already-sent notifications and the
    // convert-quote flow point at `/jobs?job=<id>`. Dropping it here would make
    // the redirect unreachable for the tier that follows those links most.
    expect(isFieldOperationalPath("/jobs")).toBe(true);
    expect(isFieldOperationalPath("/jobs/123")).toBe(true);
  });

  it("allows the personal time clock", () => {
    expect(isFieldOperationalPath("/time")).toBe(true);
    expect(isFieldOperationalPath("/time/history")).toBe(true);
  });

  it("blocks every other CRM surface", () => {
    for (const path of ["/contacts", "/opportunities", "/campaigns", "/billing", "/", "/jobsy"]) {
      expect(isFieldOperationalPath(path)).toBe(false);
    }
  });
});

describe("canSeeNavItem — field technician is fail-closed to operational routes", () => {
  it("shows only operational routes to field techs, even with all capabilities", () => {
    expect(canSeeNavItem(navItem("/jobs"), "field", canAll)).toBe(true);
    expect(canSeeNavItem(navItem("/calendar"), "field", canAll)).toBe(true);
    expect(canSeeNavItem(navItem("/time", "attendance:use"), "field", canAll)).toBe(true);
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
    expect(canSeeNavItem(navItem("/time", "attendance:use"), "lead", canAll)).toBe(true);
  });

  it("a newly added CRM nav item does not leak to leads either", () => {
    expect(canSeeNavItem(navItem("/brand-new-feature"), "lead", canAll)).toBe(false);
  });
});

describe("real nav items under the on-site tiers", () => {
  const contacts = allNavItems.find((i) => i.url === "/contacts")!;
  const calendar = allNavItems.find((i) => i.url === "/calendar")!;
  const upsell = allNavItems.find((i) => i.url === "/upsell")!;
  const time = allNavItems.find((i) => i.url === "/time")!;
  const scorecard = allNavItems.find((i) => i.url === "/scorecard")!;

  it("hides CRM surfaces but shows Calendar and Time & Attendance", () => {
    expect(canSeeNavItem(contacts, "field", canAll)).toBe(false);
    expect(canSeeNavItem(calendar, "field", canAll)).toBe(true);
    expect(canSeeNavItem(time, "field", (capability) => capability === "attendance:use")).toBe(
      true,
    );
  });

  it("has one schedule entry, not a separate Jobs board", () => {
    // Jobs and appointments share `/calendar` now and `/jobs` redirects there,
    // so a second nav entry would be two doors into the same room.
    expect(allNavItems.filter((i) => i.url === "/jobs")).toHaveLength(0);
    expect(allNavItems.filter((i) => i.url === "/calendar")).toHaveLength(1);
  });

  it("shows 'Sell add-on' to a crew lead and hides it from a plain technician", () => {
    // The allowlist alone is not enough here: /upsell is operational for both
    // tiers, so the capability gate is what separates them.
    const canSell = (c: string) => c === "upsell:sell" || c === "jobs:read";
    const jobsOnly = (c: string) => c === "jobs:read";
    expect(canSeeNavItem(upsell, "lead", canSell as typeof canAll)).toBe(true);
    expect(canSeeNavItem(upsell, "field", jobsOnly as typeof canAll)).toBe(false);
  });

  it("keeps employee activity scorecards behind reports access", () => {
    const canReport = (capability: string) => capability === "reports:view";
    expect(canSeeNavItem(scorecard, "admin", canReport as typeof canAll)).toBe(true);
    expect(canSeeNavItem(scorecard, "manager", () => false)).toBe(false);
    expect(canSeeNavItem(scorecard, "field", canAll)).toBe(false);
  });
});

describe('setupNavItem (first-run "Finish setup" entry)', () => {
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

describe("Landscape Lighting builder nav item", () => {
  const designer = allNavItems.find((i) => i.title === "Landscape Lighting");

  it("has a dedicated, searchable entry in the Sales section", () => {
    expect(designer).toBeDefined();
    expect(designer!.url).toBe("/landscape-lighting");
    expect(designer!.sidebar).toBe(true);
    expect(designer!.commandPalette).toBe(true);
    expect(designer!.requires).toBe("quotes:read");
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

  it("is registered with a festive accent and quote gate", () => {
    expect(christmas).toBeDefined();
    // Named for the seasonal estimator workflow it fronts.
    expect(christmas!.title).toBe("Christmas Light Estimator");
    // The seasonal tab must read as visually distinct (drives the tinted icon).
    expect(christmas!.accent).toBe("christmas");
    // Gated like the other quoting surfaces without exposing invoices.
    expect(christmas!.requires).toBe("quotes:read");
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

describe("canonical direct-route capability matrix", () => {
  const routes = [
    "/agents",
    "/agents/create",
    "/agents/practice",
    "/automations",
    "/experiments",
    "/experiments/new",
    "/campaigns",
    "/campaigns/sms/new",
    "/offers",
    "/offers/new",
    "/billing",
    "/catalog",
    "/reports",
    "/settings",
    "/onboarding",
    "/calendar",
    "/upsell",
    "/time",
  ] as const;

  const expectedByRole: Record<string, readonly (typeof routes)[number][]> = {
    owner: routes,
    admin: routes,
    manager: routes.filter(
      (route) => !["/agents/create", "/reports", "/onboarding"].includes(route),
    ),
    dispatcher: routes.filter(
      (route) => !["/agents/create", "/reports", "/onboarding"].includes(route),
    ),
    sales_rep: [
      "/agents",
      "/agents/practice",
      "/automations",
      "/experiments",
      "/experiments/new",
      "/campaigns",
      "/campaigns/sms/new",
      "/offers",
      "/offers/new",
      "/settings",
      "/calendar",
      "/upsell",
      "/time",
    ],
    member: [
      "/agents",
      "/agents/practice",
      "/automations",
      "/experiments",
      "/campaigns",
      "/offers",
      "/settings",
      "/calendar",
      "/upsell",
      "/time",
    ],
    lead_technician: ["/calendar", "/upsell", "/time"],
    technician: ["/calendar", "/time"],
  };

  it.each(Object.entries(expectedByRole))(
    "%s can enter exactly its permitted feature routes",
    (role, allowedRoutes) => {
      const capabilityCheck = (capability: Capability) => can(role, capability);

      for (const route of routes) {
        expect(canAccessAppPath(route, roleTier(role), capabilityCheck), `${role}: ${route}`).toBe(
          allowedRoutes.includes(route),
        );
      }
    },
  );

  it("uses longest-prefix read requirements plus explicit management overrides", () => {
    expect(findNavItemForPath("/agents/practice/session")).toMatchObject({
      url: "/agents/practice",
      requires: "crm:read",
    });
    expect(directManagementCapabilityForPath("/agents/create")).toBe("workspace:manage");
    expect(directManagementCapabilityForPath("/agents/agent-id")).toBe("workspace:manage");
    expect(directManagementCapabilityForPath("/campaigns/email/new")).toBe("outreach:write");
    expect(directManagementCapabilityForPath("/offers/offer-id")).toBe("outreach:write");
    expect(directManagementCapabilityForPath("/experiments/new")).toBe("outreach:write");
  });
});
