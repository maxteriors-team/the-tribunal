import { describe, expect, it } from "vitest";

import { type Capability, type Tier, can, roleTier, TIER_CAPABILITIES } from "./permissions";

describe("roleTier", () => {
  const cases: [string, Tier][] = [
    ["owner", "admin"],
    ["admin", "admin"],
    ["manager", "manager"],
    ["dispatcher", "manager"],
    ["sales_rep", "sales"],
    ["lead_technician", "lead"],
    ["technician", "field"],
    ["member", "tech"],
  ];
  it.each(cases)("maps %s → %s", (role, tier) => {
    expect(roleTier(role)).toBe(tier);
  });

  it("fails closed to field for unknown/empty/null roles", () => {
    expect(roleTier("wizard")).toBe("field");
    expect(roleTier("")).toBe("field");
    expect(roleTier(null)).toBe("field");
    expect(roleTier(undefined)).toBe("field");
  });
});

const ALL_CAPABILITIES: Capability[] = [
  "workspace:manage",
  "members:manage",
  "crm:read",
  "crm:write",
  "pipeline:write_own",
  "pipeline:write",
  "jobs:read",
  "jobs:write",
  "comms:send",
  "comms:manage",
  "billing:read",
  "billing:write",
  "reports:view",
  "outreach:write",
  "locations:manage",
  "upsell:sell",
  "upsell:sell_uncapped",
];

const ADMIN_CAPABILITIES = [...ALL_CAPABILITIES];
const MANAGER_CAPABILITIES: Capability[] = [
  "crm:read",
  "crm:write",
  "pipeline:write_own",
  "pipeline:write",
  "jobs:read",
  "jobs:write",
  "comms:send",
  "billing:read",
  "billing:write",
  "outreach:write",
  "locations:manage",
  "upsell:sell",
  "upsell:sell_uncapped",
];

const ROLE_CAPABILITY_MATRIX = {
  owner: ADMIN_CAPABILITIES,
  admin: ADMIN_CAPABILITIES,
  manager: MANAGER_CAPABILITIES,
  dispatcher: MANAGER_CAPABILITIES,
  sales_rep: [
    "crm:read",
    "pipeline:write_own",
    "jobs:read",
    "comms:send",
    "outreach:write",
    "upsell:sell",
    "upsell:sell_uncapped",
  ],
  member: ["crm:read", "jobs:read", "comms:send", "upsell:sell", "upsell:sell_uncapped"],
  lead_technician: ["jobs:read", "upsell:sell"],
  technician: ["jobs:read"],
} satisfies Record<string, Capability[]>;

describe("eight-role capability matrix", () => {
  it.each(Object.entries(ROLE_CAPABILITY_MATRIX))(
    "%s has exactly its canonical grants",
    (role, expectedCapabilities) => {
      for (const capability of ALL_CAPABILITIES) {
        expect(can(role, capability), `${role}: ${capability}`).toBe(
          (expectedCapabilities as Capability[]).includes(capability),
        );
      }

      expect(new Set(TIER_CAPABILITIES[roleTier(role)])).toEqual(new Set(expectedCapabilities));
    },
  );
});

describe("capability matrix (mirror of backend)", () => {
  it("admin has every capability", () => {
    const all = new Set<Capability>(TIER_CAPABILITIES.admin);
    expect(TIER_CAPABILITIES.admin.length).toBe(all.size); // no dupes
    // admin is the superset of every other tier
    for (const tier of ["manager", "sales", "tech", "lead", "field"] as Tier[]) {
      for (const cap of TIER_CAPABILITIES[tier]) {
        expect(all.has(cap)).toBe(true);
      }
    }
  });

  it("field technicians are operational-only (jobs:read, no selling)", () => {
    expect(TIER_CAPABILITIES.field).toEqual(["jobs:read"]);
    expect(can("technician", "jobs:read")).toBe(true);
    for (const cap of [
      "crm:read",
      "crm:write",
      "pipeline:write_own",
      "comms:send",
      "billing:read",
      "reports:view",
    ] as Capability[]) {
      expect(can("technician", cap)).toBe(false);
    }
  });

  it("lead technicians are field techs who may sell on site", () => {
    // The entire delta between the two roles is one capability — a lead tech is
    // still a field worker with no contact book, price book, or pipeline.
    expect(TIER_CAPABILITIES.lead).toEqual(["jobs:read", "upsell:sell"]);
    expect(can("lead_technician", "upsell:sell")).toBe(true);
    for (const cap of [
      "crm:read",
      "billing:read",
      "comms:send",
      "jobs:write",
      "reports:view",
    ] as Capability[]) {
      expect(can("lead_technician", cap)).toBe(false);
    }
  });

  it("the crew lead is the seller the on-site proposal limit applies to", () => {
    // Office tiers sell uncapped; the lead sells under the workspace limit.
    for (const role of ["owner", "admin", "manager", "dispatcher", "sales_rep", "member"]) {
      expect(can(role, "upsell:sell_uncapped")).toBe(true);
    }
    expect(can("lead_technician", "upsell:sell_uncapped")).toBe(false);
    // The plain technician cannot sell at all, so "capped" is moot there.
    expect(can("technician", "upsell:sell_uncapped")).toBe(false);
    // Unknown roles fail closed to field, so they stay capped too.
    expect(can("wizard", "upsell:sell_uncapped")).toBe(false);
  });

  it("upsell:sell stops at the crew lead — a plain technician cannot sell", () => {
    // The business rule: regular techs do not quote, they hand the opportunity
    // to their crew lead. It is not a general grant for those who hold it: the
    // /upsell routes re-scope each call to the caller's assigned jobs and to
    // attachable price-book items.
    for (const role of [
      "owner",
      "admin",
      "manager",
      "dispatcher",
      "sales_rep",
      "lead_technician",
      "member",
    ]) {
      expect(can(role, "upsell:sell")).toBe(true);
    }
    expect(can("technician", "upsell:sell")).toBe(false);
    // Unknown roles fail closed to field, which cannot sell.
    expect(can("wizard", "upsell:sell")).toBe(false);
    expect(can("wizard", "crm:read")).toBe(false);
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

  it("sales owns its own pipeline and authors outreach, but cannot write contacts", () => {
    expect(can("sales_rep", "pipeline:write_own")).toBe(true);
    expect(can("sales_rep", "outreach:write")).toBe(true);
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

  it("outreach:write covers sales + operations but not member or field tech", () => {
    for (const role of ["owner", "admin", "manager", "dispatcher", "sales_rep"]) {
      expect(can(role, "outreach:write")).toBe(true);
    }
    for (const role of ["member", "technician"]) {
      expect(can(role, "outreach:write")).toBe(false);
    }
  });

  it("comms:send covers every tier except field; comms:manage is admin-only", () => {
    for (const role of ["admin", "manager", "sales_rep", "member"]) {
      expect(can(role, "comms:send")).toBe(true);
    }
    // Field technicians cannot message customers.
    expect(can("technician", "comms:send")).toBe(false);
    for (const role of ["manager", "sales_rep", "technician", "member"]) {
      expect(can(role, "comms:manage")).toBe(false);
    }
    expect(can("admin", "comms:manage")).toBe(true);
  });

  it("locations:manage covers admin + manager tier only", () => {
    for (const role of ["owner", "admin", "manager", "dispatcher"]) {
      expect(can(role, "locations:manage")).toBe(true);
    }
    for (const role of ["sales_rep", "technician", "member"]) {
      expect(can(role, "locations:manage")).toBe(false);
    }
  });

  it("pipeline:write implies pipeline:write_own", () => {
    for (const tier of ["admin", "manager", "sales", "tech", "field"] as Tier[]) {
      const caps = TIER_CAPABILITIES[tier];
      if (caps.includes("pipeline:write")) {
        expect(caps).toContain("pipeline:write_own");
      }
    }
  });
});
