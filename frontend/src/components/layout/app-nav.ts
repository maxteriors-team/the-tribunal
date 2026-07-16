import {
  BarChart3,
  Bell,
  BookMarked,
  BookOpen,
  CalendarCheck,
  Bot,
  Boxes,
  Calendar,
  ClipboardCheck,
  CreditCard,
  ClipboardList,
  Drama,
  FileText,
  FlaskConical,
  Gift,
  KanbanSquare,
  LayoutDashboard,
  Layers,
  Lightbulb,
  LucideIcon,
  Magnet,
  MapPin,
  Megaphone,
  Phone,
  PhoneCall,
  Receipt,
  Repeat,
  Rocket,
  Ruler,
  Settings,
  Sparkles,
  Star,
  TreePine,
  UserSearch,
  Users,
  Wrench,
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
  title: string;
  items: AppNavItem[];
  collapsible?: boolean;
  defaultOpen?: boolean;
  devOnly?: boolean;
}

/**
 * First-run setup entry (finding RF-002). Rendered at the top of the sidebar
 * only while the workspace is unconfigured, so users who skip the auto-redirect
 * to /onboarding can always find their way back to finish setup.
 */
export const setupNavItem: AppNavItem = {
  title: "Finish setup",
  url: "/onboarding",
  icon: Rocket,
  sidebar: true,
  commandPalette: true,
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
  {
    title: "Opportunities",
    url: "/opportunities",
    icon: KanbanSquare,
    sidebar: true,
    commandPalette: true,
    requires: "pipeline:write_own",
  },
  {
    title: "Quotes",
    url: "/quotes",
    icon: FileText,
    sidebar: true,
    commandPalette: true,
    requires: "billing:read",
  },
  {
    title: "Estimator",
    url: "/estimator",
    icon: Ruler,
    sidebar: true,
    commandPalette: true,
    requires: "billing:read",
  },
  {
    title: "Christmas Light Estimator",
    url: "/christmas-lights",
    icon: TreePine,
    sidebar: true,
    commandPalette: true,
    accent: "christmas",
    requires: "billing:read",
  },
  {
    title: "Invoices",
    url: "/invoices",
    icon: Receipt,
    sidebar: true,
    commandPalette: true,
    requires: "billing:read",
  },
  {
    title: "Contacts",
    url: "/contacts",
    icon: Users,
    sidebar: true,
    commandPalette: true,
  },
  {
    title: "Segments",
    url: "/segments",
    icon: Boxes,
    sidebar: true,
    commandPalette: true,
  },
  {
    title: "Campaigns",
    url: "/campaigns",
    icon: Megaphone,
    sidebar: true,
    commandPalette: true,
  },
  {
    title: "Calls",
    url: "/calls",
    icon: Phone,
    sidebar: true,
    commandPalette: true,
  },
  {
    title: "Scorecard",
    url: "/scorecard",
    icon: ClipboardList,
    sidebar: true,
    commandPalette: true,
  },
  {
    title: "Reports",
    url: "/reports",
    icon: BarChart3,
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

export const toolsNavItems: AppNavItem[] = [
  {
    title: "AI Agents",
    url: "/agents",
    icon: Bot,
    sidebar: true,
    commandPalette: true,
  },
  {
    title: "Practice / Roleplay",
    url: "/agents/practice",
    icon: Drama,
    sidebar: true,
    commandPalette: true,
  },
  {
    title: "Knowledge Base",
    url: "/knowledge",
    icon: BookOpen,
    sidebar: true,
    commandPalette: true,
  },
  {
    title: "AI Suggestions",
    url: "/suggestions",
    icon: Lightbulb,
    sidebar: true,
    commandPalette: true,
  },
  {
    title: "Offers",
    url: "/offers",
    icon: Gift,
    sidebar: true,
    commandPalette: true,
  },
  {
    title: "Reviews",
    url: "/reviews",
    icon: Star,
    sidebar: true,
    commandPalette: true,
  },
  {
    title: "Lead Magnets",
    url: "/lead-magnets",
    icon: Magnet,
    sidebar: true,
    commandPalette: true,
  },
  {
    title: "Phone Numbers",
    url: "/phone-numbers",
    icon: PhoneCall,
    sidebar: true,
    commandPalette: true,
    requires: "comms:manage",
  },
  {
    title: "Automations",
    url: "/automations",
    icon: Zap,
    sidebar: true,
    commandPalette: true,
  },
  {
    title: "Experiments",
    url: "/experiments",
    icon: FlaskConical,
    sidebar: true,
    commandPalette: true,
  },
  {
    title: "Calendar",
    url: "/calendar",
    icon: Calendar,
    sidebar: true,
    commandPalette: true,
  },
  {
    title: "Jobs",
    url: "/jobs",
    icon: Wrench,
    sidebar: true,
    commandPalette: true,
  },
  {
    title: "Recurring Jobs",
    url: "/recurring-jobs",
    icon: Repeat,
    sidebar: true,
    commandPalette: true,
    requires: "billing:read",
  },
  {
    title: "Price Book",
    url: "/catalog",
    icon: BookMarked,
    sidebar: true,
    commandPalette: true,
    requires: "billing:read",
  },
  {
    title: "Billing",
    url: "/billing",
    icon: CreditCard,
    sidebar: true,
    commandPalette: true,
    requires: "billing:read",
  },
];

export const accountNavItems: AppNavItem[] = [
  {
    title: "Settings",
    url: "/settings",
    icon: Settings,
    sidebar: true,
    commandPalette: true,
  },
];

export const appNavSections: AppNavSection[] = [
  {
    title: "Workspace",
    items: workspaceNavItems,
  },
  {
    title: "Lead Discovery",
    items: leadDiscoveryNavItems,
    collapsible: true,
    defaultOpen: true,
  },
  {
    title: "Tools",
    items: toolsNavItems,
    collapsible: true,
    defaultOpen: true,
  },
  {
    title: "Account",
    items: accountNavItems,
  },
];

export const commandPaletteNavItems = appNavSections.flatMap((section) =>
  section.items.filter((item) => item.commandPalette)
);

export const breadcrumbLabels: Record<string, string> = {
  nudges: "Nudges",
  contacts: "Contacts",
  contact: "Contact",
  campaigns: "Campaigns",
  campaign: "Campaign",
  calls: "Calls",
  scorecard: "Receptionist Scorecard",
  reports: "Reports",
  dashboard: "Dashboard",
  assistant: "Assistant",
  agents: "AI Agents",
  practice: "Practice / Roleplay",
  knowledge: "Knowledge Base",
  segments: "Segments",
  suggestions: "AI Suggestions",
  offers: "Offers",
  reviews: "Reviews",
  "lead-magnets": "Lead Magnets",
  "phone-numbers": "Phone Numbers",
  automations: "Automations",
  experiments: "Experiments",
  calendar: "Calendar",
  jobs: "Jobs",
  "recurring-jobs": "Recurring Jobs",
  catalog: "Price Book",
  billing: "Billing",
  settings: "Settings",
  "find-leads": "Find Leads",
  "find-leads-ai": "Find Leads AI",
  "ad-library": "Ad Library",
  "pending-actions": "Pending Actions",
  opportunities: "Opportunities",
  quotes: "Quotes",
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
 * Field techs get the jobs schedule and its calendar — nothing else in the CRM.
 */
export const FIELD_OPERATIONAL_PREFIXES: readonly string[] = ["/jobs", "/calendar"];

/** Whether a path is inside the field-technician operational allowlist. */
export function isFieldOperationalPath(pathname: string): boolean {
  return FIELD_OPERATIONAL_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
}

/**
 * Whether a nav item should be shown to a caller.
 *
 * Field technicians are fail-closed to an explicit operational allowlist, so a
 * newly added CRM nav item never leaks to them by default. Every other tier
 * uses the capability gate (`requires`).
 */
export function canSeeNavItem(
  item: AppNavItem,
  tier: Tier,
  can: (capability: Capability) => boolean,
): boolean {
  if (tier === "field") return isFieldOperationalPath(item.url);
  return !item.requires || can(item.requires);
}
