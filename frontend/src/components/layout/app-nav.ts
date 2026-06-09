import {
  Bell,
  Bot,
  Calendar,
  ClipboardCheck,
  CreditCard,
  ClipboardList,
  FlaskConical,
  Gauge,
  Gift,
  KanbanSquare,
  LayoutDashboard,
  Lightbulb,
  LucideIcon,
  Magnet,
  MapPin,
  Megaphone,
  Phone,
  PhoneCall,
  Settings,
  Sparkles,
  Star,
  Users,
  Zap,
} from "lucide-react";

export type AppNavBadgeKey = "nudges" | "pending-actions";

export interface AppNavItem {
  title: string;
  url: string;
  icon: LucideIcon;
  sidebar?: boolean;
  commandPalette?: boolean;
  devOnly?: boolean;
  badgeKey?: AppNavBadgeKey;
}

export interface AppNavSection {
  title: string;
  items: AppNavItem[];
  collapsible?: boolean;
  defaultOpen?: boolean;
  devOnly?: boolean;
}

export const workspaceNavItems: AppNavItem[] = [
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
  },
  {
    title: "Deal Coach",
    url: "/deal-coach",
    icon: Gauge,
    sidebar: true,
    commandPalette: true,
  },
  {
    title: "Contacts",
    url: "/contacts",
    icon: Users,
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
    title: "Billing",
    url: "/billing",
    icon: CreditCard,
    sidebar: true,
    commandPalette: true,
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
  dashboard: "Dashboard",
  assistant: "Assistant",
  agents: "AI Agents",
  suggestions: "AI Suggestions",
  offers: "Offers",
  reviews: "Reviews",
  "lead-magnets": "Lead Magnets",
  "phone-numbers": "Phone Numbers",
  automations: "Automations",
  experiments: "Experiments",
  calendar: "Calendar",
  billing: "Billing",
  settings: "Settings",
  "find-leads": "Find Leads",
  "find-leads-ai": "Find Leads AI",
  "pending-actions": "Pending Actions",
  opportunities: "Opportunities",
  new: "New",
  create: "Create",
  sms: "SMS",
  voice: "Voice",
};

export function isNavItemVisible(item: AppNavItem) {
  return !item.devOnly || process.env.NODE_ENV !== "production";
}
