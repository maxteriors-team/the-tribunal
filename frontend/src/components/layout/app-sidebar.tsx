"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronDown, LogOut, MoonStar, Search, Settings, Sun } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import {
  Fragment,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { SalesRepOnboardingGate } from "@/components/onboarding/sales-rep-onboarding-gate";
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
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
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
  SidebarTrigger,
  useSidebar,
} from "@/components/ui/sidebar";
import { NoWorkspaceGate } from "@/components/workspaces/no-workspace-gate";
import { useCapabilities } from "@/hooks/useCapabilities";
import { useIsMounted } from "@/hooks/useMounted";
import { useSetupStatus } from "@/hooks/useSetupStatus";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { nudgesApi } from "@/lib/api/nudges";
import { pendingActionsApi } from "@/lib/api/pending-actions";
import type { Capability, Tier } from "@/lib/permissions";
import { queryKeys } from "@/lib/query-keys";
import { POLL_60S } from "@/lib/query-options";
import { cn } from "@/lib/utils";
import { useAuth } from "@/providers/auth-provider";
import { useWorkspace } from "@/providers/workspace-provider";

import {
  appNavSections,
  breadcrumbLabels,
  canAccessAppPath,
  canSeeNavItem,
  findNavSectionIdForPath,
  isNavItemVisible,
  setupNavItem,
  type AppNavBadgeKey,
  type AppNavItem,
  type AppNavSection,
} from "./app-nav";
import { NewMessageNotifier } from "./new-message-notifier";
import { RecentChatsMenu } from "./recent-chats-menu";
import { WorkspaceSwitcher } from "./workspace-switcher";

const CommandPalette = dynamic(() => import("./command-palette").then((m) => m.CommandPalette), {
  ssr: false,
});

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
  tier: Tier,
  can: (capability: Capability) => boolean,
): AppNavSection[] {
  return appNavSections
    .filter((section) => !section.devOnly || process.env.NODE_ENV !== "production")
    .map((section) => ({
      ...section,
      items: section.items.filter(
        (item) => item.sidebar && isNavItemVisible(item) && canSeeNavItem(item, tier, can),
      ),
    }))
    .filter((section) => section.items.length > 0);
}

interface SidebarNavProps {
  sections: AppNavSection[];
  renderItem: (item: AppNavItem, options?: { muted?: boolean }) => ReactNode;
  /** Rendered above the sections (the first-run "Finish setup" entry). */
  leading?: ReactNode;
}

/**
 * The nav list, as an accordion: exactly one section is open at a time and the
 * section that owns the current route opens itself.
 *
 * Rendering every section expanded overflowed the viewport by ~1000px on a
 * laptop, and macOS overlay scrollbars gave no hint that anything was below the
 * fold, so most of the CRM looked like it did not exist. One open section plus
 * the other section headers fits without scrolling; when a workspace's
 * capabilities do make it scroll, the fade at the bottom edge says so.
 *
 * Lives in its own component because it needs `useSidebar()`, which is only
 * available under the provider that `AppSidebar` renders.
 */
function SidebarNav({ sections, renderItem, leading }: SidebarNavProps) {
  const pathname = usePathname();
  const { state, isMobile } = useSidebar();
  const scrollRef = useRef<HTMLDivElement>(null);
  const [hasMoreBelow, setHasMoreBelow] = useState(false);

  // The route picks the open section, and a manual toggle overrides it only for
  // as long as you stay on that route. Derived rather than synced through an
  // effect, so a deep link, a command-palette jump, or back/forward all render
  // with the right section open on the first pass.
  const activeSectionId = findNavSectionIdForPath(pathname);
  const [toggled, setToggled] = useState<{
    path: string;
    sectionId: string | null;
  } | null>(null);
  const openSectionId =
    toggled?.path === pathname ? toggled.sectionId : (activeSectionId ?? sections[0]?.id ?? null);

  // The icon rail hides section headers, so a closed section there would be
  // both invisible and unopenable. Show every item and let the rail scroll.
  const isIconRail = state === "collapsed" && !isMobile;

  const syncOverflow = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    // 1px slack: fractional scroll heights otherwise leave the cue stuck on.
    setHasMoreBelow(el.scrollTop + el.clientHeight < el.scrollHeight - 1);
  }, []);

  // Layout effect + observer: the cue has to be right on first paint and after
  // every section toggle, capability change, or window resize.
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el) return;

    syncOverflow();
    const observer = new ResizeObserver(syncOverflow);
    observer.observe(el);
    for (const child of Array.from(el.children)) observer.observe(child);

    return () => observer.disconnect();
  }, [syncOverflow, sections, openSectionId, isIconRail]);

  const sectionMenu = (section: AppNavSection) => (
    <SidebarGroupContent>
      <SidebarMenu className="gap-0.5">
        {section.items.map((item) => renderItem(item, { muted: section.devOnly || item.devOnly }))}
      </SidebarMenu>
    </SidebarGroupContent>
  );

  return (
    <div className="relative flex min-h-0 flex-1 flex-col">
      <SidebarContent
        ref={scrollRef}
        onScroll={syncOverflow}
        // gap-0: each group carries its own 4px padding, and the base 8px gap
        // between nine groups cost 64px of nav height for nothing.
        // group-data-[collapsible=icon]:overflow-y-auto: keep the rail
        // scrollable when collapsed — the base component hides overflow there,
        // which stranded every icon below the fold with no way to reach them.
        className="app-scrollbar gap-0 group-data-[collapsible=icon]:overflow-y-auto"
      >
        {leading}
        {sections.map((section) => {
          if (!section.collapsible || isIconRail) {
            return (
              <SidebarGroup key={section.id} className="py-1">
                <SidebarGroupLabel className="sticky top-0 z-10 bg-sidebar uppercase tracking-widest">
                  {section.title}
                </SidebarGroupLabel>
                {sectionMenu(section)}
              </SidebarGroup>
            );
          }

          return (
            <Collapsible
              key={section.id}
              open={openSectionId === section.id}
              onOpenChange={(open) =>
                setToggled({ path: pathname, sectionId: open ? section.id : null })
              }
              className="group/collapsible"
            >
              <SidebarGroup className="py-1">
                <CollapsibleTrigger asChild>
                  {/* A real button: the group label used to be a div, so the
                      section could not be opened by keyboard at all.
                      Only additive utilities on it — `asChild` concatenates
                      class strings without conflict resolution, so restating
                      the label's own colour/size/weight would leave two
                      competing classes and let stylesheet order decide. */}
                  <SidebarGroupLabel asChild>
                    <button
                      type="button"
                      className="sticky top-0 z-10 w-full cursor-pointer rounded-md bg-sidebar uppercase tracking-widest hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
                    >
                      {section.title}
                      <ChevronDown className="ml-auto size-4 transition-transform duration-200 group-data-[state=open]/collapsible:rotate-180 motion-reduce:transition-none" />
                    </button>
                  </SidebarGroupLabel>
                </CollapsibleTrigger>
                <CollapsibleContent>{sectionMenu(section)}</CollapsibleContent>
              </SidebarGroup>
            </Collapsible>
          );
        })}
      </SidebarContent>

      {/* Overlay scrollbars stay invisible until you scroll, so this fade is the
          only resting cue that the list continues below. */}
      <div
        aria-hidden
        className={cn(
          "pointer-events-none absolute inset-x-0 bottom-0 h-10 bg-gradient-to-t from-sidebar via-sidebar/70 to-transparent transition-opacity duration-200 motion-reduce:transition-none",
          hasMoreBelow ? "opacity-100" : "opacity-0",
        )}
      />
    </div>
  );
}

interface AppSidebarProps {
  children: ReactNode;
}

export function AppSidebar({ children }: AppSidebarProps) {
  const pathname = usePathname();
  const router = useRouter();
  const { isPending: workspacePending } = useWorkspace();
  const { user, logout } = useAuth();
  const { resolvedTheme, setTheme } = useTheme();
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
  const focusedLightingProject = /^\/(?:landscape|permanent)-lighting\/[^/]+$/.test(pathname);
  const [commandOpen, setCommandOpen] = useState(false);
  const [commandMounted, setCommandMounted] = useState(false);
  // next-themes cannot know the active theme during SSR, so `resolvedTheme` is
  // undefined on the server. Gate the theme-dependent icon behind mount so the
  // server and client render identical markup (otherwise React discards and
  // re-renders this tree with a hydration mismatch).
  const themeMounted = useIsMounted();

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
    : (user?.email?.slice(0, 2).toUpperCase() ?? "U");

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
    // Festive tint keeps the seasonal hub recognizable among monochrome items.
    const accentClass = item.accent === "christmas" ? "text-emerald-600 dark:text-emerald-400" : "";

    return (
      <SidebarMenuItem key={item.title}>
        <SidebarMenuButton
          asChild
          isActive={isActive(item.url)}
          tooltip={item.title}
          className={options?.muted ? "text-muted-foreground" : undefined}
        >
          <Link href={item.url}>
            <Icon className={`size-4${accentClass ? ` ${accentClass}` : ""}`} />
            <span>{item.title}</span>
            {renderBadge(item.badgeKey)}
          </Link>
        </SidebarMenuButton>
      </SidebarMenuItem>
    );
  };

  const { tier, can } = useCapabilities();
  const visibleSidebarSections = getVisibleSidebarSections(tier, can);
  // The setup entry is rendered outside the sections above, so it has to go
  // through the same visibility gate by hand — otherwise the field-technician
  // allowlist never filters it and a technician gets an owner-only
  // "Finish setup" link into the setup wizard.
  const showSetupNav = needsSetup && canSeeNavItem(setupNavItem, tier, can);

  const routeAllowed = workspacePending || canAccessAppPath(pathname, tier, can);

  // The shell is the direct-URL capability boundary for rendered UI. Backend
  // dependencies remain the security boundary; this prevents protected page
  // content and mutations from mounting before the API can reject them.
  useEffect(() => {
    if (routeAllowed) return;

    const fallback =
      tier === "field" || tier === "lead"
        ? "/calendar"
        : can("crm:read")
          ? "/contacts"
          : "/settings";
    router.replace(fallback);
  }, [can, routeAllowed, router, tier]);

  if (!routeAllowed) return null;

  return (
    <SidebarProvider
      key={focusedLightingProject ? "studio" : "crm"}
      defaultOpen={!focusedLightingProject}
      data-app-shell
    >
      <Sidebar
        collapsible={focusedLightingProject ? "offcanvas" : "icon"}
        className="border-r border-sidebar-border bg-gradient-to-b from-sidebar via-sidebar to-sidebar"
      >
        <SidebarHeader className="border-b border-sidebar-border">
          <WorkspaceSwitcher />
        </SidebarHeader>

        <SidebarNav
          sections={visibleSidebarSections}
          renderItem={renderSidebarItem}
          leading={
            showSetupNav ? (
              <SidebarGroup className="py-1">
                <SidebarGroupContent>
                  <SidebarMenu>{renderSidebarItem(setupNavItem)}</SidebarMenu>
                </SidebarGroupContent>
              </SidebarGroup>
            ) : null
          }
        />

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
                      <span className="truncate font-semibold">{user?.full_name || "User"}</span>
                      <span className="truncate text-xs text-muted-foreground">{user?.email}</span>
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
        <header
          className={cn(
            "h-14 shrink-0 items-center gap-2 border-b px-4",
            focusedLightingProject ? "hidden" : "flex",
          )}
        >
          <SidebarTrigger className="-ml-1" />
          <Separator orientation="vertical" className="h-4" />
          {/* Deep routes (e.g. /contacts/123/details) must not wrap the header:
              ancestor crumbs collapse on narrow screens, the current page truncates. */}
          <Breadcrumb className="min-w-0">
            <BreadcrumbList className="flex-nowrap">
              {breadcrumbs.map((crumb, index) => (
                // The separator is a sibling of the item, never a child.
                // BreadcrumbSeparator renders an <li>, and BreadcrumbItem is
                // also an <li>, so nesting them produced invalid HTML and a
                // React hydration mismatch that discarded the server-rendered
                // header. It only surfaced once a route had three crumbs, since
                // a single-crumb page renders no separator at all.
                <Fragment key={crumb.href}>
                  <BreadcrumbItem className={crumb.isLast ? "min-w-0" : "hidden sm:inline-flex"}>
                    {crumb.isLast ? (
                      <BreadcrumbPage className="gradient-heading truncate">
                        {crumb.label}
                      </BreadcrumbPage>
                    ) : (
                      <BreadcrumbLink asChild>
                        <Link href={crumb.href} className="whitespace-nowrap">
                          {crumb.label}
                        </Link>
                      </BreadcrumbLink>
                    )}
                  </BreadcrumbItem>
                  {index < breadcrumbs.length - 1 && (
                    // Hidden in lockstep with the ancestor crumb it follows, so
                    // a narrow screen shows neither a stray chevron nor a gap.
                    <BreadcrumbSeparator className="hidden sm:inline-flex" />
                  )}
                </Fragment>
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
          {/* Renders nothing; toasts inbound messages from the shared poll. */}
          <NewMessageNotifier />
          <RecentChatsMenu />
          <Button
            variant="ghost"
            size="icon"
            onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
            aria-label="Toggle theme"
          >
            {themeMounted ? (
              resolvedTheme === "dark" ? (
                <Sun className="size-4" />
              ) : (
                <MoonStar className="size-4" />
              )
            ) : (
              <span className="size-4" aria-hidden />
            )}
          </Button>
        </header>
        {commandMounted && <CommandPalette open={commandOpen} onOpenChange={setCommandOpen} />}
        <main className="app-scrollbar min-h-0 min-w-0 flex-1 overflow-x-auto overflow-y-auto">
          <SalesRepOnboardingGate />
          <SetupGate />
          <NoWorkspaceGate>{children}</NoWorkspaceGate>
        </main>
      </SidebarInset>
    </SidebarProvider>
  );
}
