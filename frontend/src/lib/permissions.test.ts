import { describe, expect, it } from "vitest";

import { type Capability, type Tier, can, roleTier, TIER_CAPABILITIES } from "./permissions";

describe("roleTier", () => {
  const cases: [string, Tier][] = [
    ["owner", "admin"],
    ["admin", "admin"],
    ["manager", "manager"],
    ["dispatcher", "manager"],
    ["sales_rep", "sales"],
    ["technician", "tech"],
    ["member", "tech"],
  ];
  it.each(cases)("maps %s → %s", (role, tier) => {
    expect(roleTier(role)).toBe(tier);
  });

  it("fails closed to tech for unknown/empty/null roles", () => {
    expect(roleTier("wizard")).toBe("tech");
    expect(roleTier("")).toBe("tech");
    expect(roleTier(null)).toBe("tech");
    expect(roleTier(undefined)).toBe("tech");
  });
});

describe("capability matrix (mirror of backend)", () => {
  it("admin has every capability", () => {
    const all = new Set<Capability>(TIER_CAPABILITIES.admin);
    expect(TIER_CAPABILITIES.admin.length).toBe(all.size); // no dupes
    // admin is the superset of every other tier
    for (const tier of ["manager", "sales", "tech"] as Tier[]) {
      for (const cap of TIER_CAPABILITIES[tier]) {
        expect(all.has(cap)).toBe(true);
      }
    }
  });

  it("reports:view is admin-only", () => {
    expect(can("admin", "reports:view")).toBe(true);
    for (const role of ["manager", "dispatcher", "sales_rep", "technician", "member"]) {
      expect(can(role, "reports:view")).toBe(false);
    }
  });

  it("manager runs operations but not reports/members/number-provisioning", () => {
    for (const cap of [
      "crm:write",
      "billing:write",
      "pipeline:write",
      "jobs:write",
      "comms:send",
    ] as Capability[]) {
      expect(can("manager", cap)).toBe(true);
    }
    for (const cap of [
      "reports:view",
      "members:manage",
      "workspace:manage",
      "comms:manage",
    ] as Capability[]) {
      expect(can("manager", cap)).toBe(false);
    }
  });

  it("sales owns only its own pipeline", () => {
    expect(can("sales_rep", "pipeline:write_own")).toBe(true);
    for (const cap of [
      "pipeline:write",
      "crm:write",
      "billing:read",
      "billing:write",
      "reports:view",
    ] as Capability[]) {
      expect(can("sales_rep", cap)).toBe(false);
    }
  });

  it("comms:send is universal; comms:manage is admin-only", () => {
    for (const role of ["admin", "manager", "sales_rep", "technician", "member"]) {
      expect(can(role, "comms:send")).toBe(true);
    }
    for (const role of ["manager", "sales_rep", "technician", "member"]) {
      expect(can(role, "comms:manage")).toBe(false);
    }
    expect(can("admin", "comms:manage")).toBe(true);
  });

  it("pipeline:write implies pipeline:write_own", () => {
    for (const tier of ["admin", "manager", "sales", "tech"] as Tier[]) {
      const caps = TIER_CAPABILITIES[tier];
      if (caps.includes("pipeline:write")) {
        expect(caps).toContain("pipeline:write_own");
      }
    }
  });
});
