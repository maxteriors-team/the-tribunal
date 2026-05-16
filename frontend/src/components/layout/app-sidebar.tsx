"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Bell,
  LayoutDashboard,
  Users,
  Megaphone,
  Phone,
  PhoneCall,
  Bot,
  Settings,
  Calendar,
  ChevronDown,
  Zap,
  LogOut,
  Headphones,
  Gift,
  Magnet,
  FlaskConical,
  MapPin,
  Sparkles,
  Lightbulb,
  MoonStar,
  Sun,
  Search,
  ClipboardCheck,
} from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTheme } from "next-themes";
import { useEffect, useState, type ReactNode } from "react";

const CommandPalette = dynamic(
  () => import("./command-palette").then((m) => m.CommandPalette),
  { ssr: false },
);
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import {
  Breadcrumb,
  BreadcrumbList,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Separator } from "@/components/ui/separator";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSub,
  SidebarMenuSubItem,
  SidebarMenuSubButton,
  SidebarProvider,
  SidebarInset,
  SidebarTrigger,
  SidebarSeparator,
} from "@/components/ui/sidebar";
import { useWorkspaceId } from "@/hooks/use-workspace-id";
import { nudgesApi } from "@/lib/api/nudges";
import { pendingActionsApi } from "@/lib/api/pending-actions";
import { queryKeys } from "@/lib/query-keys";
import { POLL_60S } from "@/lib/query-options";
import { useAuth } from "@/providers/auth-provider";

import { WorkspaceSwitcher } from "./workspace-switcher";

const mainNavItems = [
  {
    title: "Dashboard",
    url: "/dashboard",
    icon: LayoutDashboard,
  },
  {
    title: "Assistant",
    url: "/assistant",
    icon: Sparkles,
  },
  {
    title: "Nudges",
    url: "/nudges",
    icon: Bell,
  },
  {
    title: "Pending Actions",
    url: "/pending-actions",
    icon: ClipboardCheck,
  },
  {
    title: "Contacts",
    url: "/contacts",
    icon: Users,
  },
  // Opportunities hidden until feature is complete
  // {
  //   title: "Opportunities",
  //   url: "/opportunities",
  //   icon: Briefcase,
  // },
  {
    title: "Campaigns",
    url: "/campaigns",
    icon: Megaphone,
  },
  {
    title: "Calls",
    url: "/calls",
    icon: Phone,
  },
];

const managementNavItems = [
  {
    title: "AI Agents",
    url: "/agents",
    icon: Bot,
  },
  {
    title: "AI Suggestions",
    url: "/suggestions",
    icon: Lightbulb,
  },
  {
    title: "Offers",
    url: "/offers",
    icon: Gift,
  },
  {
    title: "Lead Magnets",
    url: "/lead-magnets",
    icon: Magnet,
  },
  {
    title: "Phone Numbers",
    url: "/phone-numbers",
    icon: PhoneCall,
  },
  {
    title: "Automations",
    url: "/automations",
    icon: Zap,
  },
  {
    title: "Experiments",
    url: "/experiments",
    icon: FlaskConical,
  },
  {
    title: "Calendar",
    url: "/calendar",
    icon: Calendar,
  },
];

const settingsNavItems = [
  {
    title: "Settings",
    url: "/settings",
    icon: Settings,
  },
];

const segmentLabelMap: Record<string, string> = {
  nudges: "Nudges",
  contacts: "Contacts",
  contact: "Contact",
  campaigns: "Campaigns",
  campaign: "Campaign",
  calls: "Calls",
  dashboard: "Dashboard",
  agents: "AI Agents",
  suggestions: "AI Suggestions",
  offers: "Offers",
  "lead-magnets": "Lead Magnets",
  "phone-numbers": "Phone Numbers",
  automations: "Automations",
  experiments: "Experiments",
  calendar: "Calendar",
  settings: "Settings",
  "find-leads": "Find Leads",
  "find-leads-ai": "Find Leads AI",
  "voice-test": "Voice Test",
  opportunities: "Opportunities",
  "pending-actions": "Pending Actions",
};

interface BreadcrumbSegment {
  label: string;
  href: string;
  isLast: boolean;
}

function buildBreadcrumbs(pathname: string): BreadcrumbSegment[] {
  // Root "/" redirects to Contacts
  if (pathname === "/") {
    return [{ label: "Contacts", href: "/contacts", isLast: true }];
  }

  const segments = pathname.split("/").filter(Boolean);
  const crumbs: BreadcrumbSegment[] = [];

  // Check if the first segment matches a nav item directly
  const firstSegment = segments[0];
  const firstLabel = segmentLabelMap[firstSegment];

  if (!firstLabel) {
    // Fallback: capitalise the segment
    const label =
      firstSegment.charAt(0).toUpperCase() + firstSegment.slice(1);
    crumbs.push({ label, href: `/${firstSegment}`, isLast: segments.length === 1 });
  } else {
    crumbs.push({
      label: firstLabel,
      href: `/${firstSegment}`,
      isLast: segments.length === 1,
    });
  }

  // For subsequent segments (e.g. an ID or sub-page), add a generic "Detail" crumb
  if (segments.length > 1) {
    const subSegment = segments[1];
    const subLabel =
      segmentLabelMap[subSegment] ??
      (subSegment.length > 20
        ? "Detail"
        : subSegment.charAt(0).toUpperCase() + subSegment.slice(1));
    crumbs.push({
      label: subLabel,
      href: `/${segments.slice(0, 2).join("/")}`,
      isLast: true,
    });
  }

  return crumbs;
}


interface AppSidebarProps {
  children: ReactNode;
}

export function AppSidebar({ children }: AppSidebarProps) {
  const pathname = usePathname();
  const { user, logout } = useAuth();
  const { theme, setTheme } = useTheme();
  const workspaceId = useWorkspaceId();
  const { data: nudgeStats } = useQuery({
    queryKey: queryKeys.nudges.stats(workspaceId ?? ""),
    queryFn: () => nudgesApi.getStats(workspaceId!),
    enabled: !!workspaceId,
    ...POLL_60S,
  });
  const { data: pendingActionStats } = useQuery({
    queryKey: queryKeys.pendingActions.stats(workspaceId ?? ""),
    queryFn: () => pendingActionsApi.getStats(workspaceId!),
    enabled: !!workspaceId,
    ...POLL_60S,
  });
  const breadcrumbs = buildBreadcrumbs(pathname);
  const [commandOpen, setCommandOpen] = useState(false);
  const [commandMounted, setCommandMounted] = useState(false);

  const openCommandPalette = () => {
    setCommandMounted(true);
    setCommandOpen(true);
  };

  // Global ⌘K shortcut — hoisted here so the cmdk bundle stays lazy until first open.
  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setCommandMounted(true);
        setCommandOpen((prev) => !prev);
      }
    };
    document.addEventListener("keydown", down);
    return () => document.removeEventListener("keydown", down);
  }, []);

  const isActive = (url: string) => {
    if (url === "/contacts") {
      return pathname === "/contacts" || pathname.startsWith("/contacts/");
    }
    return pathname.startsWith(url);
  };

  const userInitials = user?.full_name
    ? user.full_name
        .split(" ")
        .map((n) => n[0])
        .join("")
        .toUpperCase()
        .slice(0, 2)
    : user?.email?.slice(0, 2).toUpperCase() ?? "U";

  return (
    <SidebarProvider>
      <Sidebar collapsible="icon" className="bg-gradient-to-b from-sidebar via-sidebar to-sidebar border-r border-sidebar-border">
        <SidebarHeader className="border-b border-sidebar-border">
          <WorkspaceSwitcher />
        </SidebarHeader>

        <SidebarContent>
          <SidebarGroup>
            <SidebarGroupLabel className="text-xs uppercase tracking-widest font-semibold text-muted-foreground/60">Workspace</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {mainNavItems.map((item) => (
                  <SidebarMenuItem key={item.title}>
                    <SidebarMenuButton
                      asChild
                      isActive={isActive(item.url)}
                      tooltip={item.title}
                    >
                      <Link href={item.url}>
                        <item.icon className="size-4" />
                        <span>{item.title}</span>
                        {item.title === "Nudges" && nudgeStats && nudgeStats.pending > 0 && (
                          <span className="ml-auto flex size-5 items-center justify-center rounded-full bg-orange-500 text-[10px] font-medium text-white">
                            {nudgeStats.pending > 99 ? "99+" : nudgeStats.pending}
                          </span>
                        )}
                        {item.title === "Pending Actions" && pendingActionStats && pendingActionStats.pending > 0 && (
                          <span className="ml-auto flex size-5 items-center justify-center rounded-full bg-orange-500 text-[10px] font-medium text-white">
                            {pendingActionStats.pending > 99 ? "99+" : pendingActionStats.pending}
                          </span>
                        )}
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>

          <SidebarSeparator />

          <Collapsible defaultOpen className="group/collapsible">
            <SidebarGroup>
              <CollapsibleTrigger asChild>
                <SidebarGroupLabel className="cursor-pointer hover:bg-sidebar-accent rounded-md">
                  Find Leads
                  <ChevronDown className="ml-auto size-4 transition-transform group-data-[state=open]/collapsible:rotate-180" />
                </SidebarGroupLabel>
              </CollapsibleTrigger>
              <CollapsibleContent>
                <SidebarGroupContent>
                  <SidebarMenu>
                    <SidebarMenuItem>
                      <SidebarMenuButton
                        asChild
                        isActive={isActive("/find-leads")}
                        tooltip="Find Leads"
                      >
                        <Link href="/find-leads">
                          <MapPin className="size-4" />
                          <span>Find Leads</span>
                        </Link>
                      </SidebarMenuButton>
                      <SidebarMenuSub>
                        <SidebarMenuSubItem>
                          <SidebarMenuSubButton
                            asChild
                            isActive={isActive("/find-leads-ai")}
                          >
                            <Link href="/find-leads-ai">
                              <Sparkles className="size-4" />
                              <span>Find Leads AI</span>
                            </Link>
                          </SidebarMenuSubButton>
                        </SidebarMenuSubItem>
                      </SidebarMenuSub>
                    </SidebarMenuItem>
                  </SidebarMenu>
                </SidebarGroupContent>
              </CollapsibleContent>
            </SidebarGroup>
          </Collapsible>

          <SidebarSeparator />

          <Collapsible defaultOpen className="group/collapsible">
            <SidebarGroup>
              <CollapsibleTrigger asChild>
                <SidebarGroupLabel className="cursor-pointer hover:bg-sidebar-accent rounded-md text-xs uppercase tracking-widest font-semibold text-muted-foreground/60">
                  Tools
                  <ChevronDown className="ml-auto size-4 transition-transform group-data-[state=open]/collapsible:rotate-180" />
                </SidebarGroupLabel>
              </CollapsibleTrigger>
              <CollapsibleContent>
                <SidebarGroupContent>
                  <SidebarMenu>
                    {managementNavItems.map((item) => (
                      <SidebarMenuItem key={item.title}>
                        <SidebarMenuButton
                          asChild
                          isActive={isActive(item.url)}
                          tooltip={item.title}
                        >
                          <Link href={item.url}>
                            <item.icon className="size-4" />
                            <span>{item.title}</span>
                          </Link>
                        </SidebarMenuButton>
                      </SidebarMenuItem>
                    ))}
                  </SidebarMenu>
                  <SidebarSeparator className="my-1" />
                  <p className="px-2 py-1 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground/40">
                    Dev
                  </p>
                  <SidebarMenu>
                    <SidebarMenuItem>
                      <SidebarMenuButton
                        asChild
                        isActive={isActive("/voice-test")}
                        tooltip="Voice Test"
                        className="text-muted-foreground"
                      >
                        <Link href="/voice-test">
                          <Headphones className="size-4" />
                          <span>Voice Test</span>
                        </Link>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  </SidebarMenu>
                </SidebarGroupContent>
              </CollapsibleContent>
            </SidebarGroup>
          </Collapsible>

          <SidebarSeparator />

          <SidebarGroup className="mt-auto">
            <SidebarGroupContent>
              <SidebarMenu>
                {settingsNavItems.map((item) => (
                  <SidebarMenuItem key={item.title}>
                    <SidebarMenuButton
                      asChild
                      isActive={isActive(item.url)}
                      tooltip={item.title}
                    >
                      <Link href={item.url}>
                        <item.icon className="size-4" />
                        <span>{item.title}</span>
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        </SidebarContent>

        <SidebarFooter className="border-t border-sidebar-border">
          <SidebarMenu>
            <SidebarMenuItem>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <SidebarMenuButton size="lg">
                    <Avatar className="size-8">
                      <AvatarFallback className="bg-primary/10 text-primary">
                        {userInitials}
                      </AvatarFallback>
                    </Avatar>
                    <div className="grid flex-1 text-left text-sm leading-tight">
                      <span className="truncate font-semibold">
                        {user?.full_name || "User"}
                      </span>
                      <span className="truncate text-xs text-muted-foreground">
                        {user?.email}
                      </span>
                    </div>
                  </SidebarMenuButton>
                </DropdownMenuTrigger>
                <DropdownMenuContent
                  side="top"
                  align="start"
                  className="w-56"
                >
                  <DropdownMenuItem asChild>
                    <Link href="/settings">
                      <Settings className="mr-2 size-4" />
                      Settings
                    </Link>
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem onClick={logout}>
                    <LogOut className="mr-2 size-4" />
                    Sign out
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarFooter>
      </Sidebar>

      <SidebarInset className="h-svh overflow-hidden">
        <header className="flex h-14 shrink-0 items-center gap-2 border-b px-4">
          <SidebarTrigger className="-ml-1" />
          <Separator orientation="vertical" className="h-4" />
          <Breadcrumb>
            <BreadcrumbList>
              {breadcrumbs.map((crumb, index) => (
                <BreadcrumbItem key={crumb.href}>
                  {crumb.isLast ? (
                    <BreadcrumbPage className="gradient-heading">{crumb.label}</BreadcrumbPage>
                  ) : (
                    <>
                      <BreadcrumbLink asChild>
                        <Link href={crumb.href}>{crumb.label}</Link>
                      </BreadcrumbLink>
                      {index < breadcrumbs.length - 1 && (
                        <BreadcrumbSeparator />
                      )}
                    </>
                  )}
                </BreadcrumbItem>
              ))}
            </BreadcrumbList>
          </Breadcrumb>
          <button
            onClick={openCommandPalette}
            className="ml-auto flex items-center gap-2 rounded-lg border border-border bg-muted/50 px-3 py-1.5 text-sm text-muted-foreground hover:bg-muted cursor-pointer"
          >
            <Search className="size-3.5" />
            <span>Search...</span>
            <kbd className="ml-1 rounded border border-border bg-background px-1.5 py-0.5 font-mono text-[10px]">⌘K</kbd>
          </button>
          <Button
            variant="ghost"
            size="icon"
            className="ml-2"
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            aria-label="Toggle theme"
          >
            {theme === "dark" ? (
              <Sun className="size-4" />
            ) : (
              <MoonStar className="size-4" />
            )}
          </Button>
        </header>
        {commandMounted && (
          <CommandPalette open={commandOpen} onOpenChange={setCommandOpen} />
        )}
        <main className="flex-1 min-h-0 overflow-hidden">{children}</main>
      </SidebarInset>
    </SidebarProvider>
  );
}
