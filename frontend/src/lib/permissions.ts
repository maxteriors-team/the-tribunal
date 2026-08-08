/**
 * Capability-based access control for the dashboard UI.
 *
 * Mirror of the backend source of truth in `backend/app/core/permissions.py`.
 * The backend enforces every rule; this copy only decides what to *show* (nav
 * items, action buttons, route guards). Keep the two in lockstep — if you change
 * the matrix here, change it there (and vice versa), and update both unit tests.
 *
 * Six tiers, admin broadest → field narrowest:
 *   admin   ← owner, admin
 *   manager ← manager, dispatcher
 *   sales   ← sales_rep
 *   tech    ← member
 *   lead    ← lead_technician
 *   field   ← technician  (and any unknown/legacy role, fail-closed)
 *
 * `lead` is a crew lead on a job site, not an office role: it sees exactly what
 * `field` sees. The single difference is `upsell:sell` — a crew lead may quote
 * an add-on on site and a plain technician may not.
 *
 * Field technicians are operational-only: the jobs schedule and nothing else
 * (no contacts, pipeline, campaigns, billing/pricing, or other CRM surface),
 * and they cannot sell. A technician who spots an upsell hands it to their lead.
 *
 * `upsell:sell` widens nothing on its own — only the `/upsell` endpoints honour
 * it, and those re-scope every call to the caller's assigned jobs and to
 * attachable price-book items. Note it does NOT come with `comms:send`:
 * proposal delivery rides the scoped upsell route, so a lead technician still
 * cannot message arbitrary contacts.
 */

export type Capability =
  | "crm:read"
  | "crm:write"
  | "outreach:write"
  | "pipeline:write"
  | "pipeline:write_own"
  | "jobs:read"
  | "jobs:write"
  | "comms:send"
  | "comms:manage"
  | "billing:read"
  | "billing:write"
  | "reports:view"
  | "members:manage"
  | "workspace:manage"
  | "locations:manage"
  | "upsell:sell"
  | "upsell:sell_uncapped";

export type Tier = "admin" | "manager" | "sales" | "tech" | "lead" | "field";

const ROLE_TIERS: Record<string, Tier> = {
  owner: "admin",
  admin: "admin",
  manager: "manager",
  dispatcher: "manager",
  sales_rep: "sales",
  lead_technician: "lead",
  technician: "field",
  member: "tech",
};

const ALL_CAPABILITIES: Capability[] = [
  "crm:read",
  "crm:write",
  "outreach:write",
  "pipeline:write",
  "pipeline:write_own",
  "jobs:read",
  "jobs:write",
  "comms:send",
  "comms:manage",
  "billing:read",
  "billing:write",
  "reports:view",
  "members:manage",
  "workspace:manage",
  "locations:manage",
  "upsell:sell",
  "upsell:sell_uncapped",
];

export const TIER_CAPABILITIES: Record<Tier, Capability[]> = {
  admin: [...ALL_CAPABILITIES],
  manager: [
    "crm:read",
    "crm:write",
    "outreach:write",
    "pipeline:write",
    "pipeline:write_own",
    "jobs:read",
    "jobs:write",
    "comms:send",
    "billing:read",
    "billing:write",
    "locations:manage",
    "upsell:sell",
    "upsell:sell_uncapped",
  ],
  // Sales authors outreach (campaigns/segments/automations) but has no
  // crm:write, so it cannot delete/import contacts — mirror of the backend.
  sales: [
    "crm:read",
    "outreach:write",
    "pipeline:write_own",
    "jobs:read",
    "comms:send",
    "upsell:sell",
    "upsell:sell_uncapped",
  ],
  tech: ["crm:read", "jobs:read", "comms:send", "upsell:sell", "upsell:sell_uncapped"],
  // Crew lead: the field tier's visibility exactly, plus the authority to sell
  // on site, held to the workspace's proposal limit. Still no contact book,
  // price book, or pipeline.
  lead: ["jobs:read", "upsell:sell"],
  // Field technicians: the jobs schedule and nothing else. No selling.
  field: ["jobs:read"],
};

/** Resolve a role string to its access tier (unknown/legacy → `field`, fail-closed). */
export function roleTier(role: string | null | undefined): Tier {
  if (!role) return "field";
  return ROLE_TIERS[role] ?? "field";
}

/** Return true when `role` is granted `capability`. */
export function can(role: string | null | undefined, capability: Capability): boolean {
  return TIER_CAPABILITIES[roleTier(role)].includes(capability);
}
