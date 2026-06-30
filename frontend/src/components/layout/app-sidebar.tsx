"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronDown, LogOut, MoonStar, Search, Settings, Sun } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTheme } from "next-themes";
import { Fragment, useEffect, useState, type ReactNode } from "react";

import { SetupGate } from "@/components/onboarding/setup-gate";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
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
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarSeparator,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import { NoWorkspaceGate } from "@/components/workspaces/no-workspace-gate";
import { useCapabilities } from "@/hooks/useCapabilities";
import { useSetupStatus } from "@/hooks/useSetupStatus";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { nudgesApi } from "@/lib/api/nudges";
import { pendingActionsApi } from "@/lib/api/pending-actions";
import type { Capability } from "@/lib/permissions";
import { queryKeys } from "@/lib/query-keys";
import { POLL_60S } from "@/lib/query-options";
import { useAuth } from "@/providers/auth-provider";

import {
  appNavSections,
  breadcrumbLabels,
  isNavItemVisible,
  setupNavItem,
  type AppNavBadgeKey,
  type AppNavItem,
  type AppNavSection,
} from "./app-nav";
import { WorkspaceSwitcher } from "./workspace-switcher";

const CommandPalette = dynamic(
  () => import("./command-palette").then((m) => m.CommandPalette),
  { ssr: false }
);

interface BreadcrumbSegment {
  label: string;
  href: string;
  isLast: boolean;
}

function formatSegmentLabel(segment: string, isFirstSegment: boolean) {
  const knownLabel = breadcrumbLabels[segment];

  if (knownLabel) {
    return knownLabel;
  }

  if (!isFirstSegment && segment.length > 20) {
    return "Detail";
  }

  return segment
    .split("-")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function buildBreadcrumbs(pathname: string): BreadcrumbSegment[] {
  if (pathname === "/") {
    return [{ label: "Contacts", href: "/contacts", isLast: true }];
  }

  const segments = pathname.split("/").filter(Boolean);

  return segments.map((segment, index) => ({
    label: formatSegmentLabel(segment, index === 0),
    href: `/${segments.slice(0, index + 1).join("/")}`,
    isLast: index === segments.length - 1,
  }));
}

function getVisibleSidebarSections(
  can: (capability: Capability) => boolean,
): AppNavSection[] {
  return appNavSections
    .filter((section) => !section.devOnly || process.env.NODE_ENV !== "production")
    .map((section) => ({
      ...section,
      items: section.items.filter(
        (item) =>
          item.sidebar &&
          isNavItemVisible(item) &&
          (!item.requires || can(item.requires)),
      ),
    }))
    .filter((section) => section.items.length > 0);
}

interface AppSidebarProps {
  children: ReactNode;
}

export function AppSidebar({ children }: AppSidebarProps) {
  const pathname = usePathname();
  const { user, logout } = useAuth();
  const { theme, setTheme } = useTheme();
  const workspaceId = useWorkspaceId();
  const { needsSetup } = useSetupStatus();
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
    return pathname === url || pathname.startsWith(`${url}/`);
  };

  const userInitials = user?.full_name
    ? user.full_name
        .split(" ")
        .map((n) => n[0])
        .join("")
        .toUpperCase()
        .slice(0, 2)
    : user?.email?.slice(0, 2).toUpperCase() ?? "U";

  const badgeCounts: Partial<Record<AppNavBadgeKey, number>> = {
    nudges: nudgeStats?.pending ?? 0,
    "pending-actions": pendingActionStats?.pending ?? 0,
  };

  const renderBadge = (badgeKey?: AppNavBadgeKey) => {
    if (!badgeKey) return null;

    const count = badgeCounts[badgeKey] ?? 0;

    if (count <= 0) return null;

    return (
      <span className="ml-auto flex size-5 items-center justify-center rounded-full bg-orange-500 text-[10px] font-medium text-white">
        {count > 99 ? "99+" : count}
      </span>
    );
  };

  const renderSidebarItem = (item: AppNavItem, options?: { muted?: boolean }) => {
    const Icon = item.icon;

    return (
      <SidebarMenuItem key={item.title}>
        <SidebarMenuButton
          asChild
          isActive={isActive(item.url)}
          tooltip={item.title}
          className={options?.muted ? "text-muted-foreground" : undefined}
        >
          <Link href={item.url}>
            <Icon className="size-4" />
            <span>{item.title}</span>
            {renderBadge(item.badgeKey)}
          </Link>
        </SidebarMenuButton>
      </SidebarMenuItem>
    );
  };

  const renderSectionMenu = (section: AppNavSection) => (
    <SidebarGroupContent>
      <SidebarMenu>
        {section.items.map((item) =>
          renderSidebarItem(item, { muted: section.devOnly || item.devOnly })
        )}
      </SidebarMenu>
    </SidebarGroupContent>
  );

  const { can } = useCapabilities();
  const visibleSidebarSections = getVisibleSidebarSections(can);

  return (
    <SidebarProvider data-app-shell>
      <Sidebar
        collapsible="icon"
        className="border-r border-sidebar-border bg-gradient-to-b from-sidebar via-sidebar to-sidebar"
      >
        <SidebarHeader className="border-b border-sidebar-border">
          <WorkspaceSwitcher />
        </SidebarHeader>

        <SidebarContent className="app-scrollbar">
          {needsSetup && (
            <SidebarGroup>
              <SidebarGroupContent>
                <SidebarMenu>{renderSidebarItem(setupNavItem)}</SidebarMenu>
              </SidebarGroupContent>
            </SidebarGroup>
          )}
          {visibleSidebarSections.map((section, index) => (
            <Fragment key={section.title}>
              {index > 0 && <SidebarSeparator />}
              {section.collapsible ? (
                <Collapsible
                  defaultOpen={section.defaultOpen}
                  className="group/collapsible"
                >
                  <SidebarGroup>
                    <CollapsibleTrigger asChild>
                      <SidebarGroupLabel className="cursor-pointer rounded-md text-xs font-semibold uppercase tracking-widest text-muted-foreground/60 hover:bg-sidebar-accent">
                        {section.title}
                        <ChevronDown className="ml-auto size-4 transition-transform group-data-[state=open]/collapsible:rotate-180" />
                      </SidebarGroupLabel>
                    </CollapsibleTrigger>
                    <CollapsibleContent>{renderSectionMenu(section)}</CollapsibleContent>
                  </SidebarGroup>
                </Collapsible>
              ) : (
                <SidebarGroup>
                  <SidebarGroupLabel className="text-xs font-semibold uppercase tracking-widest text-muted-foreground/60">
                    {section.title}
                  </SidebarGroupLabel>
                  {renderSectionMenu(section)}
                </SidebarGroup>
              )}
            </Fragment>
          ))}
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
                <DropdownMenuContent side="top" align="start" className="w-56">
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
                    <BreadcrumbPage className="gradient-heading">
                      {crumb.label}
                    </BreadcrumbPage>
                  ) : (
                    <>
                      <BreadcrumbLink asChild>
                        <Link href={crumb.href}>{crumb.label}</Link>
                      </BreadcrumbLink>
                      {index < breadcrumbs.length - 1 && <BreadcrumbSeparator />}
                    </>
                  )}
                </BreadcrumbItem>
              ))}
            </BreadcrumbList>
          </Breadcrumb>
          <button
            onClick={openCommandPalette}
            className="ml-auto flex cursor-pointer items-center gap-2 rounded-lg border border-border bg-muted/50 px-3 py-1.5 text-sm text-muted-foreground hover:bg-muted"
          >
            <Search className="size-3.5" />
            <span>Search...</span>
            <kbd className="ml-1 rounded border border-border bg-background px-1.5 py-0.5 font-mono text-[10px]">
              ⌘K
            </kbd>
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
        <main className="app-scrollbar min-h-0 flex-1 overflow-y-auto overflow-x-hidden">
          <SetupGate />
          <NoWorkspaceGate>{children}</NoWorkspaceGate>
        </main>
      </SidebarInset>
    </SidebarProvider>
  );
}
