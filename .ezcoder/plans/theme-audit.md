# Product Light + Dark Theme Audit

## Summary

The product's light and dark themes are defined in `globals.css` using CSS custom properties and are toggled via `next-themes` (`ThemeProvider attribute="class"`). The audit found **5 categories of issues** that need to be fixed across ~50 component files.

---

## Issue 1 — Dark Mode toggle in Settings is broken (functional bug)

**File:** `frontend/src/components/settings/profile-settings-tab.tsx` (line ~193)

The "Dark Mode" card in the Appearance section renders a `<Switch defaultChecked />` that has no event handler — it doesn't actually toggle the theme. The sidebar already has a working theme toggle button that calls `setTheme`, but the settings page toggle is completely disconnected.

**Fix:** Import `useTheme` from `next-themes`, derive `isDark` from `theme === "dark"`, and call `setTheme(isDark ? "light" : "dark")` on switch change. Also remove `defaultChecked` and use `checked={isDark}`.

---

## Issue 2 — Missing `--info` CSS variable for blue semantic states

**File:** `frontend/src/app/globals.css`

Many components use `text-blue-500`, `bg-blue-500/10` etc. for informational/neutral states (incoming calls, scheduled appointments, info boxes, "Speaking" state). The theme has no blue token. Without it, blue elements won't adapt between light and dark.

**Fix:** Add `--info` and expose it in `@theme inline`:

```css
/* In :root */
--info: #3b82f6;

/* In .dark */
--info: #60a5fa;

/* In @theme inline */
--color-info: var(--info);
```

This gives us `text-info`, `bg-info`, `bg-info/10`, `border-info/20`, etc. as Tailwind utilities.

---

## Issue 3 — Raw Tailwind palette colors used instead of theme tokens

**Scope:** ~50 component and page files throughout `frontend/src/components/` and `frontend/src/app/`.

Components use hardcoded Tailwind palette classes (e.g. `text-green-500`, `bg-yellow-50`, `text-red-600`, `text-purple-500`, `text-gray-400`) instead of the semantic tokens the theme provides. In dark mode these often lack `dark:` variants, so they look broken when switching themes. The theme provides:

| Semantic meaning | Old raw classes | New theme token |
|---|---|---|
| Success / active / completed | `green-*` | `success` |
| Error / failed / destructive | `red-*` | `destructive` |
| Warning / pending / caution | `yellow-*`, `amber-*`, `orange-*` | `warning` |
| Informational / incoming / scheduled | `blue-*` | `info` (new — see Issue 2) |
| Primary / AI / agent / active | `purple-*` | `primary` |
| Neutral / inactive / muted | `gray-*` | `muted-foreground` / `muted` |

### Replacement rules

```
bg-green-50  → bg-success/10
bg-green-100 → bg-success/10
text-green-500/600/700/800 → text-success
border-green-200/300 → border-success/20
bg-green-500/10 → bg-success/10
ring-green-500 → ring-success
bg-green-500 (solid) → bg-success
bg-green-600 hover:bg-green-700 → bg-success hover:bg-success/90

bg-red-50  → bg-destructive/10
text-red-500/600/700 → text-destructive
border-red-200/300 → border-destructive/20
bg-red-500/10 → bg-destructive/10
bg-red-500 (solid) → bg-destructive

bg-yellow-50/yellow-100 → bg-warning/10
text-yellow-500/600/700/amber-600 → text-warning
border-yellow-200/amber-200 → border-warning/20
bg-yellow-500/10 / bg-amber-500/5 → bg-warning/10
bg-orange-500/10 → bg-warning/10 (orange = warning in this theme)
text-orange-500 → text-warning

bg-blue-50 → bg-info/10
text-blue-500/600/700 → text-info
border-blue-200 → border-info/20
bg-blue-500/10 → bg-info/10

text-purple-500/600/700 → text-primary
bg-purple-500/10 → bg-primary/10
border-purple-500/20 → border-primary/20

text-gray-400/500/600 → text-muted-foreground
bg-gray-400 (solid dot) → bg-muted-foreground
bg-gray-500/10 → bg-muted
text-gray-500 → text-muted-foreground
border-gray-500/20 → border-border
bg-gray-50/100 → bg-muted
```

Also remove all `dark:bg-green-950/20`, `dark:text-green-200` etc. paired overrides — these become unnecessary once the theme token is used.

### Files to update

**`frontend/src/components/`**

- `actions/followup-section.tsx` — `text-blue-500` → `text-info`
- `actions/quick-actions-section.tsx` — `text-green-500` → `text-success`
- `agents/ab-test-dashboard.tsx` — green/yellow/blue raw colors + `dark:` pairs
- `agents/agent-form-utils.ts` — `text-green-600`, `text-yellow-600`, `text-red-600`
- `agents/agents-list.tsx` — `bg-green-500`/`bg-gray-400` (status dots), `bg-blue-500/10`
- `agents/embed-agent-dialog.tsx` — `text-green-500`
- `agents/prompt-improvement-dialog.tsx` — green + `dark:` pairs
- `agents/prompt-performance-chart.tsx` — `bg-green-500`
- `agents/system-prompt-step.tsx` — `text-green-600`, `text-yellow-600`
- `agents/voice-test-dialog.tsx` — green/yellow/gray/red status colors
- `automations/automations-page.tsx` — yellow/blue/purple/green
- `calendar/calendar-page.tsx` — green/amber
- `calls/active-call.tsx` — full `statusConfig` object (blue/yellow/green/gray/red/orange)
- `calls/calls-list.tsx` — blue/green
- `calls/transcript-viewer.tsx` — purple/blue (bot/user speaker colors)
- `calcom/calcom-embed.tsx` — `text-red-500`
- `campaigns/campaign-detail.tsx` — red/green
- `campaigns/guarantee-progress.tsx` — blue/green/red
- `campaigns/offer-selector.tsx` — green/blue + `dark:` pairs
- `campaigns/sms-campaign-wizard.tsx` — green
- `campaigns/sms-fallback-step.tsx` — blue/purple + `dark:` pairs
- `campaigns/voice-campaign-wizard.tsx` — green
- `contacts/contact-card.tsx` — blue + `dark:` pair
- `contacts/contact-sidebar.tsx` — green/amber
- `contacts/contacts-list.tsx` — green/yellow/gray/purple
- `contacts/find-leads-ai-page.tsx` — green/yellow/red/blue/gray/purple
- `contacts/find-leads-page.tsx` — green/yellow/blue
- `contacts/import-contacts-dialog.tsx` — green/yellow/red
- `contacts/scrape-leads-dialog.tsx` — green/yellow/red/blue
- `conversation/message-item.tsx` — green/red/yellow/blue/purple speaker colors
- `dashboard/appointment-performance-card.tsx` — green/yellow/red/blue
- `dashboard/dashboard-page.tsx` — green/red/yellow/blue/purple
- `experiments/experiments-list.tsx` — green
- `experiments/test-analytics.tsx` — green/blue
- `offers/ai-offer-writer.tsx` — green
- `offers/lead-magnet-selector.tsx` — blue/purple + `dark:` pairs
- `offers/offer-preview.tsx` — green/red/amber/yellow/blue
- `offers/value-stack-builder.tsx` — green + `dark:` pairs
- `opportunities/opportunities-board.tsx` — green/red/blue status
- `opportunities/opportunities-list.tsx` — green/red/yellow/blue
- `opportunities/opportunity-detail-sheet.tsx` — green/red/blue/purple/gray
- `settings/integration-config-dialog.tsx` — green/red
- `settings/integrations-settings-tab.tsx` — red
- `suggestions/campaign-report-card.tsx` — amber/red + `dark:` pairs
- `suggestions/experiment-dashboard.tsx` — green/yellow/blue + `dark:` pairs

**`frontend/src/app/`**

- `lead-magnets/page.tsx` — green/blue
- `offers/page.tsx` — green/blue
- `suggestions/page.tsx` — blue/green
- `experiments/[id]/page.tsx` — gray/green/yellow/purple status colors
- `invite/[token]/page.tsx` — yellow + `dark:` pairs
- `p/offers/[slug]/page.tsx` — green/orange + `dark:` pairs

---

## Issue 4 — NeuralNetwork hardcoded default colors

**File:** `frontend/src/components/effects/neural-network/NeuralNetwork.tsx`

```ts
const DEFAULT_PRIMARY = "#7058e3";   // correct — matches --primary
const DEFAULT_ACCENT  = "#5ee5b3";   // dark-only — light theme has #0fa66e for --success
```

The component is only used in `app/demo/neural/page.tsx` (a dev demo). It accepts `primaryColor` and `accentColor` props so the defaults only matter when no props are passed.

**Fix:** Update `DEFAULT_ACCENT` to `"#0fa66e"` (the light theme's `--success`), and add a `useEffect` in `NeuralNetwork` that reads `getComputedStyle(document.documentElement)` to dynamically pick `--primary` and `--success` CSS values when no explicit props are provided. This makes the demo page automatically respond to theme switches.

---

## Issue 5 — Landing page hardcoded colors (intentionally static — NO ACTION NEEDED)

`frontend/src/components/landing/` and `frontend/src/app/p/landing/layout.tsx` use many hardcoded hex colors (`#1a1523`, `#f3eff8`, `#5c566b`, etc.). This is **intentional**: the landing page layout (`/p/landing`) does **not** use the app's `ThemeProvider` — it has its own `QueryClientProvider` only. The landing page is a fixed light-mode marketing page with a deliberate bespoke design. No changes needed.

---

## Issue 6 — Suggestions queue categorical colors (intentionally multi-color — NO ACTION NEEDED)

`frontend/src/components/suggestions/suggestions-queue.tsx` `getMutationTypeBadge` uses 8 distinct palette colors (orange, blue, red, purple, pink, green, cyan, amber) to differentiate suggestion types. All 8 already have correct `dark:` pairs. This is intentional categorical differentiation — do not reduce to theme tokens.

---

## Exceptions (unchanged)

- `frontend/src/app/embed/[publicId]/` — standalone embedded voice widget with its own dynamic theming from `AgentConfig.primary_color`; does not and should not use app theme tokens
- `frontend/src/app/embed/[publicId]/chat/` — same as above

---

## Implementation Order

1. **`globals.css`** — add `--info` variable (needed first; other files depend on it)
2. **`profile-settings-tab.tsx`** — fix Dark Mode toggle (quick self-contained fix)
3. **`NeuralNetwork.tsx`** — fix default accent + add CSS variable reading
4. **UI component files** — update all raw color classes in alphabetical order by directory:
   - `actions/`, `agents/`, `automations/`, `calendar/`, `calls/`, `calcom/`
   - `campaigns/`, `contacts/`, `conversation/`, `dashboard/`
   - `experiments/`, `offers/`, `opportunities/`, `settings/`, `suggestions/`
   - `app/experiments/`, `app/invite/`, `app/lead-magnets/`, `app/offers/`, `app/p/offers/`, `app/suggestions/`
5. **Run** `cd frontend && npm run lint && npm run build` — fix all errors

---

## Verification Criteria

- `npm run lint` and `npm run build` pass with zero errors
- Switching theme in the sidebar toggles all semantic colors (success → green shifts between `#0fa66e` and `#5ee5b3`, etc.)
- The Dark Mode switch in Settings → Profile → Appearance actually toggles the theme
- No `dark:bg-green-*`, `dark:text-green-*`, `dark:bg-red-*`, `dark:bg-yellow-*`, `dark:bg-blue-*` classes remain in non-landing app components (they're replaced by self-adapting theme tokens)
- No `bg-green-50`, `bg-red-50`, `bg-yellow-50`, `bg-blue-50` light-only backgrounds remain in app components
