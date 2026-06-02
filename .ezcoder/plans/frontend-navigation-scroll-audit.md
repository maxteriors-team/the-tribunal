# Frontend navigation, side menu, and themed scrollbar audit plan

## Summary
The app has two overlapping layout issues that explain “random pages” losing scrollbars or side menus:

- `frontend/src/components/layout/app-sidebar.tsx:523` locks the shell content with `<SidebarInset className="h-svh overflow-hidden">`, and `frontend/src/components/layout/app-sidebar.tsx:572` locks the inner content with `<main className="flex-1 min-h-0 overflow-hidden">`. Any route that does not explicitly create its own `h-full overflow-y-auto` or `ScrollArea` becomes clipped with no page scrollbar. Examples found include `DashboardPage`, `AgentsList` through `ResourceListLayout`, `CampaignsList`, `ExperimentsList`, `CallsList`, `SettingsPage`, `OffersPage`, `LeadMagnetsPage`, `BillingContent`, `RealtorDashboardContent`, `SuggestionsPage`, and `AutomationsPage`.
- Several authenticated app routes are not using the app shell at all, so the side nav/header disappears. Confirmed missing shell: `frontend/src/app/agents/[id]/page.tsx`, `frontend/src/app/pending-actions/page.tsx`, `frontend/src/app/voice-test/page.tsx`, and `frontend/src/app/lead-magnets/new/page.tsx`.

The durable fix is to make the app shell provide the default themed scroll container, keep explicit full-height pages intact, centralize navigation so sidebar and command palette stop drifting, and theme every scrollbar path to match the PRESTYJ light/dark design.

## Audit findings

### Shell scroll ownership
- `frontend/src/components/layout/app-sidebar.tsx:523` sets `SidebarInset` to `h-svh overflow-hidden`.
- `frontend/src/components/layout/app-sidebar.tsx:572` sets the inner `<main>` to `flex-1 min-h-0 overflow-hidden`.
- This means content only scrolls if the page itself opts in; many plain content pages render `p-6 space-y-6` under a hidden shell and get clipped.
- Good explicit full-height patterns should be preserved:
  - `frontend/src/app/contacts/page.tsx:9` wraps `ContactsPage` with `h-full overflow-hidden`, and `frontend/src/components/contacts/contacts-page.tsx:350` owns an inner `ScrollArea`.
  - `frontend/src/app/contacts/[id]/page.tsx:41` and `frontend/src/components/layout/conversation-layout.tsx:27-90` own full-height columns.
  - `frontend/src/components/contacts/find-leads-page.tsx:121-169` and `frontend/src/components/contacts/find-leads-ai-page.tsx:168-218` use fixed-height internal result panes.
  - `frontend/src/components/nudges/nudges-page.tsx:139` and `frontend/src/components/pending-actions/pending-actions-page.tsx:114` already own `h-full overflow-y-auto`.
  - `frontend/src/components/opportunities/opportunities-page.tsx:27-70` owns full-height board/list tabs.
  - `frontend/src/app/assistant/page.tsx:7-15` and `frontend/src/components/assistant/assistant-chat.tsx:396` own chat-area scrolling.

### Scrollbar behavior and theming
- Installed `@radix-ui/react-scroll-area` is `1.2.10`.
- Dependency source confirms `ScrollArea` defaults to `type = 'hover'`, so Radix custom scrollbars are hidden except hover/scroll interaction.
- Dependency source confirms Radix hides native viewport scrollbars with injected `[data-radix-scroll-area-viewport]` CSS.
- Our wrapper `frontend/src/components/ui/scroll-area.tsx:8-28` does not override `type`, so all local `ScrollArea` usages inherit hidden-until-hover custom bars.
- Native scroll containers currently rely on browser/OS defaults and can look off-theme: shell main, `SidebarContent`, `PendingActionsPage`, `NudgesPage`, table wrappers, dialog contents, and assorted `overflow-y-auto` panels.
- The theme variables in `frontend/src/app/globals.css:62-174` already define light/dark values for background, muted, border, primary, and sidebar colors; themed scrollbar tokens should derive from these rather than hard-coded colors.

### Authenticated routes missing the app shell
- `frontend/src/app/agents/[id]/page.tsx:318-350` returns loading/error/main content without importing or wrapping in `AppSidebar`. Direct links from `frontend/src/components/agents/agents-list.tsx:421` and `:500` make this a real side-menu disappearance bug.
- `frontend/src/app/pending-actions/page.tsx:1-5` returns `<PendingActionsPage />` directly, despite the sidebar linking to `/pending-actions` from `frontend/src/components/layout/app-sidebar.tsx:107-109`.
- `frontend/src/app/voice-test/page.tsx` has no `AppSidebar` import/wrapper, despite the sidebar linking to `/voice-test` from `frontend/src/components/layout/app-sidebar.tsx:443`.
- `frontend/src/app/lead-magnets/new/page.tsx` has no `AppSidebar` import/wrapper and is an authenticated workspace feature route.
- Public or standalone routes should remain outside the shell: `/login`, `/invite/[token]`, `/onboarding`, `/p/*`, and `/embed/*`.

### App shell nav omissions and drift
- Sidebar workspace nav currently includes Dashboard, Assistant, Nudges, Pending Actions, Contacts, Campaigns, and Calls in `frontend/src/components/layout/app-sidebar.tsx:90-132`.
- Sidebar tools nav currently includes AI Agents, AI Suggestions, Offers, Lead Magnets, Phone Numbers, Automations, Experiments, and Calendar in `frontend/src/components/layout/app-sidebar.tsx:134-175`.
- Find Leads and Find Leads AI are in a collapsible group at `frontend/src/components/layout/app-sidebar.tsx:361-401`.
- Settings is in its own group at `frontend/src/components/layout/app-sidebar.tsx:177-183` and `:457-476`.
- Existing authenticated top-level pages not represented in sidebar:
  - `/billing` at `frontend/src/app/billing/page.tsx`, reachable from billing flows.
  - `/realtor-dashboard` at `frontend/src/app/realtor-dashboard/page.tsx`, reachable from billing/onboarding.
  - `/opportunities` exists but is intentionally hidden via commented code at `frontend/src/components/layout/app-sidebar.tsx:116-121`; leave hidden unless product wants it surfaced.
  - `/dev/components` should remain dev-only and hidden from production nav.
- Command palette drift is significant: `frontend/src/components/layout/command-palette.tsx:14-27` omits Assistant, Nudges, Pending Actions, Lead Magnets, Phone Numbers, Experiments, Billing, Realtor Dashboard, and Voice Test, and duplicates sidebar nav data by hand.

### Breadcrumb omissions
`segmentLabelMap` in `frontend/src/components/layout/app-sidebar.tsx:185-207` is missing labels for `assistant`, `billing`, `realtor-dashboard`, `new`, `create`, `sms`, and `voice`, which creates generic breadcrumbs on known routes.

### Sidebar overflow and collapse concerns
- `SidebarContent` at `frontend/src/components/ui/sidebar.tsx:371-383` is scrollable on expanded desktop/mobile, but hidden in icon collapse through `group-data-[collapsible=icon]:overflow-hidden`.
- Settings uses `mt-auto` inside the same scrollable content at `frontend/src/components/layout/app-sidebar.tsx:457`; with enough nav items or shorter screens, this can place lower items awkwardly. Prefer a single scrollable nav section plus footer-only user/profile content.
- Mobile sidebar uses Radix `SheetContent` and `SidebarContent`; link navigation usually unmounts the sheet on route change, but shell-missing routes make the menu appear to disappear after navigation.

## Proposed implementation

### Centralized navigation data
Create `frontend/src/components/layout/app-nav.ts` as a pure data module with typed nav metadata.

- Export `AppNavItem` with `title`, `url`, `icon`, optional `devOnly`, `sidebar`, `commandPalette`, and optional badge keys for Nudges/Pending Actions.
- Export sidebar sections for Workspace, Lead Discovery, Tools, Account, and Dev.
- Include Dashboard, Assistant, Nudges, Pending Actions, Contacts, Campaigns, Calls, Find Leads, Find Leads AI, AI Agents, AI Suggestions, Offers, Lead Magnets, Phone Numbers, Automations, Experiments, Calendar, Billing, Realtor Dashboard, Settings, and Voice Test.
- Keep `/opportunities` hidden unless product decides to expose it; if hidden, include a comment/flag explaining it is intentionally incomplete.
- Export `breadcrumbLabels` for all top-level and known sub-route path segments, including `assistant`, `billing`, `realtor-dashboard`, `new`, `create`, `sms`, and `voice`.
- Refactor `frontend/src/components/layout/app-sidebar.tsx` and `frontend/src/components/layout/command-palette.tsx` to consume this shared source.

### Shell-owned default scrolling
Update `frontend/src/components/layout/app-sidebar.tsx` so the shell owns a normal, themed vertical scroll region by default.

- Keep `SidebarInset` viewport-limited with `h-svh overflow-hidden`.
- Change inner `<main>` from `flex-1 min-h-0 overflow-hidden` to `flex-1 min-h-0 overflow-y-auto overflow-x-hidden` plus an app scrollbar class if a class-based approach is used.
- Preserve explicit full-height pages by keeping their `h-full min-h-0 overflow-hidden` wrappers where they intentionally own nested scrolling.
- Avoid broad page rewrites; the shell change should restore scrolling for ordinary pages.

### Themed native and Radix scrollbars
Update `frontend/src/app/globals.css` and `frontend/src/components/ui/scroll-area.tsx` so all scrollbars match the light/dark theme.

- Add scrollbar CSS tokens under `:root` and `.dark`, such as `--scrollbar-track`, `--scrollbar-thumb`, and `--scrollbar-thumb-hover`, derived from existing variables like `--background`, `--muted`, `--border`, `--muted-foreground`, `--primary`, and sidebar equivalents.
- Add global native scrollbar styling for Firefox and WebKit: `scrollbar-width`, `scrollbar-color`, `::-webkit-scrollbar`, `::-webkit-scrollbar-track`, `::-webkit-scrollbar-thumb`, and thumb hover. Keep tracks subtle and thumbs visible enough to signal scrollability.
- Ensure native scrollbar CSS also applies to `frontend/src/components/ui/table.tsx:9-12`, dialog contents using `overflow-y-auto`, `SidebarContent`, and feature panes using raw `overflow-y-auto`.
- Default `ScrollAreaPrimitive.Root` in `frontend/src/components/ui/scroll-area.tsx` to `type="auto"` while preserving caller overrides.
- Update `ScrollBar` and `ScrollAreaThumb` classes to use the same theme tokens rather than only `bg-border`, including both vertical and horizontal orientations.
- If visual checks show `/embed/*` widgets are polluted by global scrollbar CSS, scope the scrollbar rules to the authenticated app shell by adding a wrapper attribute/class in `AppSidebar` and applying the themed native rules under that scope. Start with neutral tokens and verify before adding extra scoping.

### Missing app-shell wrappers
Wrap authenticated route pages that currently drop the side menu.

- `frontend/src/app/agents/[id]/page.tsx`: import `AppSidebar` and wrap loading, error, and main return branches. Keep the form content under a shell-scroll-friendly `min-h-full p-6` style.
- `frontend/src/app/pending-actions/page.tsx`: import `AppSidebar` and wrap `<PendingActionsPage />`. The component already has `h-full overflow-y-auto`.
- `frontend/src/app/voice-test/page.tsx`: import `AppSidebar`, wrap the returned voice test layout, and replace the root `-m-4 flex h-[calc(100vh-3.5rem)] md:-m-6 lg:-m-8` with `flex h-full min-h-0` or equivalent shell-aware sizing.
- `frontend/src/app/lead-magnets/new/page.tsx`: import `AppSidebar` and wrap both the no-workspace state and main wizard. Replace `container max-w-4xl py-8` with a centered shell-friendly wrapper such as `mx-auto w-full max-w-4xl p-6 md:py-8`.

### Targeted viewport math cleanup
Normalize only the routes with explicit shell-internal viewport math or nested scroll traps.

- `frontend/src/app/experiments/new/page.tsx:108` uses `h-[calc(100vh-4rem)]`; replace with `h-full min-h-0`.
- `frontend/src/app/campaigns/sms/new/page.tsx:149` and `frontend/src/app/campaigns/voice/new/page.tsx:124` use the same `h-[calc(100vh-4rem)]`; replace with `h-full min-h-0`.
- `frontend/src/app/experiments/[id]/page.tsx:112` and `:121` use `h-screen` inside the shell; replace with `h-full` or `min-h-full` so loading/error states do not exceed the content area.
- `frontend/src/app/experiments/[id]/page.tsx:132` already uses `flex flex-col h-full overflow-auto`; leave intact unless visual checks reveal double scrollbars.
- `frontend/src/components/calls/calls-list.tsx:254` uses `ScrollArea className="h-[calc(100vh-480px)] min-h-[300px]"`; keep for now unless visual checks reveal it clips, because it is not required for the core missing-scrollbar fix.

### Command palette coverage
Update `frontend/src/components/layout/command-palette.tsx` to consume shared nav data.

- Include all command-palette-eligible authenticated routes from the shared nav source.
- Align any dev-only filtering with the sidebar so Voice Test and dev routes do not drift.
- Remove the duplicated local `navItems` array.

## Risks
- Changing shell main to default scroll can create nested scrollbars on routes that already own scroll. Mitigation: fixed-height pages retain `h-full overflow-hidden`, and representative contacts/find-leads/assistant pages get visual checks.
- Global native scrollbar CSS can affect public embed and landing pages. Mitigation: use neutral theme-derived tokens first, then scope the rules to the app shell if visual checks show pollution.
- Centralizing nav icons in a new module can accidentally pull client-only code into server components. Mitigation: keep `app-nav.ts` pure data with lucide icon references and no hooks/state.
- Adding Billing and Realtor Dashboard to visible sidebar might be a product decision. Default plan is to show them because the user asked every nav item should be present; if they should remain secondary, include them in breadcrumbs/command palette and document the intentional hidden state.

## Verification
Because changes touch `.tsx` and `globals.css` frontend files, run the required project checks after implementation.

- Run `cd frontend && npm run lint` and fix all reported issues.
- Run `cd frontend && npm run build` and fix all reported issues.
- Use `.gg/eyes/visual-web.sh` against representative fixed-height pages: `/contacts`, `/assistant`, `/find-leads`, and `/voice-test`.
- Use `.gg/eyes/visual-web.sh` against representative default-scroll pages: `/dashboard`, `/agents`, `/settings`, `/lead-magnets`, and `/pending-actions`.
- Confirm side nav/header are present on `/agents/<id>` if a local test agent exists, `/pending-actions`, `/voice-test`, and `/lead-magnets/new`.
- Confirm themed scrollbar appearance in both dark and light mode on at least one native scroll container and one Radix `ScrollArea` container.
- If authenticated data, dev server, or seed records are unavailable locally, document the blocker and still complete lint/build verification.

## Steps
1. Add `frontend/src/components/layout/app-nav.ts` with shared nav sections, command-palette items, breadcrumb labels, route visibility flags, and badge metadata.
2. Refactor `frontend/src/components/layout/app-sidebar.tsx` to consume shared nav data, expose missing expected nav entries for Billing and Realtor Dashboard unless intentionally hidden, update breadcrumb labels, and change the shell `<main>` to a themed default vertical scroll region.
3. Refactor `frontend/src/components/layout/command-palette.tsx` to consume shared nav data so it includes all expected app routes and cannot drift from the sidebar.
4. Update `frontend/src/app/globals.css` and `frontend/src/components/ui/scroll-area.tsx` so native and Radix scrollbars use shared light/dark theme tokens and Radix scroll areas default to discoverable overflow behavior.
5. Wrap missing authenticated routes in `AppSidebar`: `frontend/src/app/agents/[id]/page.tsx`, `frontend/src/app/pending-actions/page.tsx`, `frontend/src/app/voice-test/page.tsx`, and `frontend/src/app/lead-magnets/new/page.tsx`.
6. Replace brittle shell-internal viewport math in affected wizard/detail pages with `h-full min-h-0` or shell-scroll-friendly wrappers.
7. Run `cd frontend && npm run lint`; fix all reported issues.
8. Run `cd frontend && npm run build`; fix all reported issues.
9. Perform visual/runtime checks with `.gg/eyes/visual-web.sh` on representative default-scroll and fixed-height pages, including a dark/light themed scrollbar check, and document any auth/dev-server/data blockers.