import {
  BarChart3,
  Bell,
  BookMarked,
  BookOpen,
  CalendarCheck,
  CalendarSync,
  Bot,
  Boxes,
  Calendar,
  ClipboardCheck,
  Clock3,
  CreditCard,
  ClipboardList,
  Drama,
  FileText,
  FlaskConical,
  Gift,
  Handshake,
  KanbanSquare,
  LayoutDashboard,
  Layers,
  Lightbulb,
  LucideIcon,
  Magnet,
  MapPin,
  Megaphone,
  Package,
  Phone,
  PhoneCall,
  Receipt,
  Rocket,
  Ruler,
  Settings,
  Sparkles,
  Star,
  Tag,
  Target,
  TreePine,
  UserSearch,
  Users,
  Zap,
} from "lucide-react";

import type { Capability, Tier } from "@/lib/permissions";

export type AppNavBadgeKey = "nudges" | "pending-actions";

/** Optional seasonal accent that visually distinguishes a nav item. */
export type AppNavAccent = "christmas";

export interface AppNavItem {
  title: string;
  url: string;
  icon: LucideIcon;
  sidebar?: boolean;
  commandPalette?: boolean;
  devOnly?: boolean;
  badgeKey?: AppNavBadgeKey;
  /**
   * Festive accent that tints the item's icon so it stands out among the
   * otherwise-monochrome nav (used for the seasonal Christmas Lights hub).
   */
  accent?: AppNavAccent;
  /**
   * Capability required to see this item. When set, the sidebar and command
   * palette hide it unless the caller's role grants the capability (mirrors the
   * backend gate in `app/api/deps.py`). Omit for items every member can reach.
   */
  requires?: Capability;
}

export interface AppNavSection {
  /**
   * Stable key for the sidebar's open/closed state. Never derive it from the
   * title — renaming a section must not silently reset which group is open.
   */
  id: string;
  title: string;
  items: AppNavItem[];
  /**
   * Collapsible sections render closed unless they own the active route (the
   * sidebar keeps exactly one open). Sections are deliberately kept small — see
   * `appNavSections` — so an open section plus every other section's header
   * still fits a 700px-tall laptop window without scrolling.
   */
  collapsible?: boolean;
  devOnly?: boolean;
}

/**
 * First-run setup entry (finding RF-002). Rendered at the top of the sidebar
 * only while the workspace is unconfigured, so users who skip the auto-redirect
 * to /onboarding can always find their way back to finish setup.
 *
 * Setup configures the whole workspace (calendar credentials, lead import,
 * first campaign), so it carries `workspace:manage` like any other admin
 * surface and must be run through `canSeeNavItem` — `/onboarding` is outside the
 * field-technician allowlist, so field techs never see it.
 */
export const setupNavItem: AppNavItem = {
  title: "Finish setup",
  url: "/onboarding",
  icon: Rocket,
  sidebar: true,
  commandPalette: true,
  requires: "workspace:manage",
};

export const workspaceNavItems: AppNavItem[] = [
  {
    title: "Today",
    url: "/today",
    icon: CalendarCheck,
    sidebar: true,
    commandPalette: true,
  },
  {
    title: "Time & Attendance",
    url: "/time",
    icon: Clock3,
    sidebar: true,
    commandPalette: true,
    requires: "attendance:use",
  },
  {
    title: "Dashboard",
    url: "/dashboard",
    icon: LayoutDashboard,
    sidebar: true,
    commandPalette: true,
  },
  {
    title: "Assistant",
    url: "/assistant",
    icon: Sparkles,
    sidebar: true,
    commandPalette: true,
  },
  {
    title: "Nudges",
    url: "/nudges",
    icon: Bell,
    sidebar: true,
    commandPalette: true,
    badgeKey: "nudges",
  },
  {
    title: "Pending Actions",
    url: "/pending-actions",
    icon: ClipboardCheck,
    sidebar: true,
    commandPalette: true,
    badgeKey: "pending-actions",
  },
];

export const salesNavItems: AppNavItem[] = [
  {
    title: "Opportunities",
    url: "/opportunities",
    icon: KanbanSquare,
    sidebar: true,
    commandPalette: true,
    requires: "pipeline:write_own",
  },
  {
    title: "Quotes & Estimates",
    url: "/quotes",
    icon: FileText,
    sidebar: true,
    commandPalette: true,
    requires: "quotes:read",
  },
  {
    // Landscape design is a distinct, visual sales workflow: it needs a direct
    // front door rather than hiding behind the Quotes table. Mixed-service work
    // can still use the designer tab inside Quotes.
    title: "Landscape Lighting",
    url: "/landscape-lighting",
    icon: Ruler,
    sidebar: true,
    commandPalette: true,
    requires: "quotes:read",
  },
  {
    // Seasonal launcher folded into the unified Quotes & Estimates hub; kept in
    // the command palette (and reachable by URL) but out of the sidebar so there
    // is one obvious quoting/estimates home instead of competing estimator tabs.
    title: "Christmas Light Estimator",
    url: "/christmas-lights",
    icon: TreePine,
    sidebar: false,
    commandPalette: true,
    accent: "christmas",
    requires: "quotes:read",
  },
  {
    title: "Invoices",
    url: "/invoices",
    icon: Receipt,
    sidebar: true,
    commandPalette: true,
    requires: "billing:read",
  },
];

export const customerNavItems: AppNavItem[] = [
  {
    title: "Contacts",
    url: "/contacts",
    icon: Users,
    sidebar: true,
    commandPalette: true,
  },
  {
    // Recipient selection already lives inline in the campaign builder
    // (filters + search) and on Contacts via "Save as Segment", so a
    // standalone sidebar entry is a duplicate entry point. Kept in the command
    // palette (and reachable by URL) for managing the saved segments that the
    // AI growth workflow, prebooking audiences, and the outbound auto-draft
    // worker depend on.
    title: "Segments",
    url: "/segments",
    icon: Boxes,
    sidebar: false,
    commandPalette: true,
  },
  {
    title: "Campaigns",
    url: "/campaigns",
    icon: Megaphone,
    sidebar: true,
    commandPalette: true,
    requires: "crm:read",
  },
  {
    title: "Calls",
    url: "/calls",
    icon: Phone,
    sidebar: true,
    commandPalette: true,
  },
];

export const insightsNavItems: AppNavItem[] = [
  {
    title: "Scorecard",
    url: "/scorecard",
    icon: ClipboardList,
    sidebar: true,
    commandPalette: true,
    requires: "reports:view",
  },
  {
    title: "Reports",
    url: "/reports",
    icon: BarChart3,
    sidebar: true,
    commandPalette: true,
    requires: "reports:view",
  },
  {
    title: "Sales Performance",
    url: "/reports/sales",
    icon: Target,
    sidebar: true,
    commandPalette: true,
    requires: "reports:view",
  },
];

export const leadDiscoveryNavItems: AppNavItem[] = [
  {
    title: "Find Leads",
    url: "/find-leads",
    icon: MapPin,
    sidebar: true,
    commandPalette: true,
  },
  {
    title: "Find Leads AI",
    url: "/find-leads-ai",
    icon: Sparkles,
    sidebar: true,
    commandPalette: true,
  },
  {
    title: "Ad Library",
    url: "/find-leads/ad-library",
    icon: Layers,
    sidebar: true,
    commandPalette: true,
  },
  {
    title: "People Search",
    url: "/find-leads/people",
    icon: UserSearch,
    sidebar: true,
    commandPalette: true,
  },
];

export const automationNavItems: AppNavItem[] = [
  {
    title: "AI Agents",
    url: "/agents",
    icon: Bot,
    sidebar: true,
    commandPalette: true,
    requires: "crm:read",
  },
  {
    title: "Practice / Roleplay",
    url: "/agents/practice",
    icon: Drama,
    sidebar: true,
    commandPalette: true,
    requires: "crm:read",
  },
  {
    title: "Knowledge Base",
    url: "/knowledge",
    icon: BookOpen,
    sidebar: true,
    commandPalette: true,
    requires: "crm:read",
  },
  {
    title: "AI Suggestions",
    url: "/suggestions",
    icon: Lightbulb,
    sidebar: true,
    commandPalette: true,
    requires: "crm:read",
  },
  {
    title: "Automations",
    url: "/automations",
    icon: Zap,
    sidebar: true,
    commandPalette: true,
    requires: "crm:read",
  },
  {
    title: "Experiments",
    url: "/experiments",
    icon: FlaskConical,
    sidebar: true,
    commandPalette: true,
    requires: "crm:read",
  },
];

export const marketingNavItems: AppNavItem[] = [
  {
    title: "Offers",
    url: "/offers",
    icon: Gift,
    sidebar: true,
    commandPalette: true,
    requires: "crm:read",
  },
  {
    title: "Reviews",
    url: "/reviews",
    icon: Star,
    sidebar: true,
    commandPalette: true,
  },
  {
    // The named people behind the referral channel. Visibility mirrors the
    // backend read gate (any workspace member); the write affordances inside the
    // page are gated separately on `crm:write`, which matches the manager-and-up
    // role required by the write routes.
    title: "Referral Partners",
    url: "/referral-partners",
    icon: Handshake,
    sidebar: true,
    commandPalette: true,
    requires: "crm:read",
  },
  {
    title: "Lead Magnets",
    url: "/lead-magnets",
    icon: Magnet,
    sidebar: true,
    commandPalette: true,
  },
];

export const operationsNavItems: AppNavItem[] = [
  {
    // The single schedule surface: appointments and field jobs on one grid.
    // `/jobs` used to be a second, job-only calendar and now redirects here.
    title: "Calendar",
    url: "/calendar",
    icon: Calendar,
    sidebar: true,
    commandPalette: true,
  },
  {
    // Reachable by every tier that can sell (see `upsell:sell`), and the only
    // CRM surface besides jobs/calendar a field technician can open.
    title: "Sell add-on",
    url: "/upsell",
    icon: Tag,
    sidebar: true,
    commandPalette: true,
    requires: "upsell:sell",
  },
  {
    title: "Service Plans",
    url: "/service-plans",
    icon: CalendarSync,
    sidebar: true,
    commandPalette: true,
    requires: "billing:read",
  },
  {
    title: "Inventory",
    url: "/inventory",
    icon: Package,
    sidebar: true,
    commandPalette: true,
    // jobs:read, not billing:read: a crew lead checking what is left on the
    // truck is an operational question. The API redacts every cost field for
    // callers below billing:read, and the table drops those columns entirely.
    requires: "jobs:read",
  },
  {
    title: "Price Book",
    url: "/catalog",
    icon: BookMarked,
    sidebar: true,
    commandPalette: true,
    requires: "billing:read",
  },
];

export const accountNavItems: AppNavItem[] = [
  {
    title: "Phone Numbers",
    url: "/phone-numbers",
    icon: PhoneCall,
    sidebar: true,
    commandPalette: true,
    requires: "comms:manage",
  },
  {
    title: "Billing",
    url: "/billing",
    icon: CreditCard,
    sidebar: true,
    commandPalette: true,
    requires: "billing:read",
  },
  {
    title: "Settings",
    url: "/settings",
    icon: Settings,
    sidebar: true,
    commandPalette: true,
  },
];

/**
 * Sidebar information architecture.
 *
 * Every section is collapsible and the sidebar keeps exactly one open, so the
 * resting nav height is `(sections - 1) x 40px + the open section`. Two
 * sections used to hold 16 and 17 items: with both expanded the nav measured
 * 1651px against ~570-770px of usable height on a laptop, which left 20-24 of
 * the 39 destinations off-screen behind an overlay scrollbar that never
 * appeared until you scrolled. Keep sections at **six items or fewer** so the
 * open section plus every other section's header still fits a 700px-tall
 * window; split a section rather than growing it past that.
 */
export const appNavSections: AppNavSection[] = [
  {
    id: "workspace",
    title: "Workspace",
    items: workspaceNavItems,
    collapsible: true,
  },
  {
    id: "customers",
    title: "Customers",
    items: customerNavItems,
    collapsible: true,
  },
  {
    id: "sales",
    title: "Sales",
    items: salesNavItems,
    collapsible: true,
  },
  {
    id: "insights",
    title: "Insights",
    items: insightsNavItems,
    collapsible: true,
  },
  {
    id: "lead-discovery",
    title: "Lead Discovery",
    items: leadDiscoveryNavItems,
    collapsible: true,
  },
  {
    id: "marketing",
    title: "Marketing",
    items: marketingNavItems,
    collapsible: true,
  },
  {
    id: "automation",
    title: "AI & Automation",
    items: automationNavItems,
    collapsible: true,
  },
  {
    id: "operations",
    title: "Operations",
    items: operationsNavItems,
    collapsible: true,
  },
  {
    id: "account",
    title: "Account",
    items: accountNavItems,
    collapsible: true,
  },
];

/** Every registered nav item, in sidebar order. */
export const allNavItems: AppNavItem[] = appNavSections.flatMap((section) => section.items);

export const commandPaletteNavItems = allNavItems.filter((item) => item.commandPalette);

/**
 * Longest-prefix nav match for a route. Query strings on nav entries are ignored
 * because `usePathname()` only supplies the pathname.
 */
export function findNavItemForPath(pathname: string): AppNavItem | null {
  let bestItem: AppNavItem | null = null;
  let bestLength = -1;

  for (const item of [...allNavItems, setupNavItem]) {
    const url = item.url.split("?")[0];
    const matches = pathname === url || pathname.startsWith(`${url}/`);

    if (matches && url.length > bestLength) {
      bestItem = item;
      bestLength = url.length;
    }
  }

  return bestItem;
}

/**
 * Id of the section that owns `pathname`, or null when no nav item matches.
 * Longest URL match wins, so `/reports/sales` resolves to its dedicated item
 * rather than the shorter `/reports` prefix.
 */
export function findNavSectionIdForPath(pathname: string): string | null {
  const item = findNavItemForPath(pathname);
  if (!item) return null;

  return appNavSections.find((section) => section.items.includes(item))?.id ?? null;
}

export const breadcrumbLabels: Record<string, string> = {
  nudges: "Nudges",
  contacts: "Contacts",
  contact: "Contact",
  campaigns: "Campaigns",
  campaign: "Campaign",
  calls: "Calls",
  scorecard: "Scorecards",
  reports: "Reports",
  sales: "Sales Performance",
  dashboard: "Dashboard",
  assistant: "Assistant",
  agents: "AI Agents",
  practice: "Practice / Roleplay",
  knowledge: "Knowledge Base",
  segments: "Segments",
  suggestions: "AI Suggestions",
  offers: "Offers",
  reviews: "Reviews",
  "referral-partners": "Referral Partners",
  partner: "Partner",
  "lead-magnets": "Lead Magnets",
  "phone-numbers": "Phone Numbers",
  automations: "Automations",
  experiments: "Experiments",
  calendar: "Calendar",
  jobs: "Jobs",
  // "Upsell" is internal jargon; the technician using this screen calls it
  // selling an add-on.
  upsell: "Sell add-on",
  "service-plans": "Service Plans",
  catalog: "Price Book",
  inventory: "Inventory",
  billing: "Billing",
  settings: "Settings",
  "find-leads": "Find Leads",
  "find-leads-ai": "Find Leads AI",
  "ad-library": "Ad Library",
  "pending-actions": "Pending Actions",
  time: "Time & Attendance",
  opportunities: "Opportunities",
  quotes: "Quotes & Estimates",
  estimator: "Light Designer",
  "landscape-lighting": "Landscape Lighting",
  invoices: "Invoices",
  "christmas-lights": "Christmas Light Estimator",
  new: "New",
  create: "Create",
  sms: "SMS",
  voice: "Voice",
};

export function isNavItemVisible(item: AppNavItem) {
  return !item.devOnly || process.env.NODE_ENV !== "production";
}

/**
 * Route prefixes a field technician (operational-only tier) may see and reach.
 * Field techs get the schedule and the on-site upsell flow — nothing else in
 * the CRM.
 *
 * `/upsell` is safe to expose to the narrowest tier because the surface behind it
 * is scoped server-side (assigned jobs + attachable catalog items only); see
 * `backend/app/api/v1/upsell.py`. This list is UX, not the security boundary.
 *
 * `/jobs` no longer has a screen of its own — it redirects to `/calendar` — but
 * it stays listed so an existing bookmark or a `?job=` deep link still resolves
 * for the tier that most often follows one.
 */
/**
 * Paths an on-site tier (`field`, `lead`) may reach. `/upsell` is listed here
 * but is additionally capability-gated in {@link canSeeNavItem}, so only a crew
 * lead sees it.
 */
export const FIELD_OPERATIONAL_PREFIXES: readonly string[] = [
  "/jobs",
  "/calendar",
  "/upsell",
  "/time",
];

/** Whether a path is inside the field-technician operational allowlist. */
export function isFieldOperationalPath(pathname: string): boolean {
  return FIELD_OPERATIONAL_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
}

/**
 * Whether a nav item should be shown to a caller.
 *
 * On-site tiers (`field` and `lead`) are fail-closed to an explicit operational
 * allowlist, so a newly added CRM nav item never leaks to them by default. Most
 * nav items carry no `requires` at all, so without the allowlist a crew lead
 * would see the whole CRM sidebar and click into pages the API then refuses.
 *
 * The allowlist is necessary but not sufficient: allowlisted items are still
 * capability-gated, which is what keeps "Sell add-on" visible to a `lead` and
 * hidden from a plain `field` technician who cannot quote.
 */
export function canSeeNavItem(
  item: AppNavItem,
  tier: Tier,
  can: (capability: Capability) => boolean,
): boolean {
  const allowed = !item.requires || can(item.requires);
  if (tier === "field" || tier === "lead") {
    return isFieldOperationalPath(item.url) && allowed;
  }
  return allowed;
}

/** Capability required only by a direct management screen under a readable area. */
export function directManagementCapabilityForPath(pathname: string): Capability | null {
  const segments = pathname.split("/").filter(Boolean);

  if (segments[0] === "agents" && segments.length > 1 && segments[1] !== "practice") {
    return "workspace:manage";
  }

  if (segments[0] === "campaigns" && segments.at(-1) === "new") {
    return "outreach:write";
  }

  if (segments[0] === "offers" && segments.length > 1) {
    return "outreach:write";
  }

  if (segments[0] === "experiments" && segments[1] === "new") {
    return "outreach:write";
  }

  return null;
}

/**
 * Shared direct-URL decision used by the app shell and unit tests.
 *
 * Field and lead-technician tiers stay fail-closed to their explicit operational
 * allowlist. Other roles must satisfy both the nav area's read capability and any
 * narrower management-screen requirement.
 */
export function canAccessAppPath(
  pathname: string,
  tier: Tier,
  can: (capability: Capability) => boolean,
): boolean {
  if (tier === "field" || tier === "lead") {
    if (!isFieldOperationalPath(pathname)) return false;
  }

  const item = findNavItemForPath(pathname);
  if (item && !canSeeNavItem(item, tier, can)) return false;

  const managementCapability = directManagementCapabilityForPath(pathname);
  return !managementCapability || can(managementCapability);
}
