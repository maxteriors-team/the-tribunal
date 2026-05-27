import {
  Bell,
  Bot,
  Calendar,
  ClipboardCheck,
  CreditCard,
  FlaskConical,
  Gift,
  Headphones,
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
    title: "Contacts",
    url: "/contacts",
    icon: Users,
    sidebar: true,
    commandPalette: true,
  },
  // Opportunities remains intentionally hidden until the feature is complete.
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
  {
    title: "Realtor Dashboard",
    url: "/realtor-dashboard",
    icon: LayoutDashboard,
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

export const devNavItems: AppNavItem[] = [
  {
    title: "Voice Test",
    url: "/voice-test",
    icon: Headphones,
    sidebar: true,
    commandPalette: true,
    devOnly: true,
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
  {
    title: "Dev",
    items: devNavItems,
    devOnly: true,
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
  dashboard: "Dashboard",
  assistant: "Assistant",
  agents: "AI Agents",
  suggestions: "AI Suggestions",
  offers: "Offers",
  "lead-magnets": "Lead Magnets",
  "phone-numbers": "Phone Numbers",
  automations: "Automations",
  experiments: "Experiments",
  calendar: "Calendar",
  billing: "Billing",
  "realtor-dashboard": "Realtor Dashboard",
  settings: "Settings",
  "find-leads": "Find Leads",
  "find-leads-ai": "Find Leads AI",
  "voice-test": "Voice Test",
  opportunities: "Opportunities",
  "pending-actions": "Pending Actions",
  new: "New",
  create: "Create",
  sms: "SMS",
  voice: "Voice",
};

export function isNavItemVisible(item: AppNavItem) {
  return !item.devOnly || process.env.NODE_ENV !== "production";
}
