# Unified calendar design

## Design read

- **Surface:** Data-dense operations dashboard.
- **Audience:** Dispatchers coordinating a workspace from desktop, plus field workers checking their own day from a phone.
- **Single job:** Answer “what is happening, and who owns it?” without reconciling separate appointment and job screens.
- **Risk:** Missing or exposing someone else’s work is operational and privacy-sensitive; the API is the visibility boundary and the UI never expands it.
- **Content:** Appointment and job titles, start times, customers, statuses, a dispatch backlog, and long service names.
- **Constraints:** Reuse the existing shadcn-derived cards/buttons, Tailwind tokens, Lucide icons, dialogs, query keys, and role capability matrix. No new dependency or visual system.

## Thesis

**One grid, two entry species.** Appointments and scheduled jobs share chronological day cells, but remain distinguishable without relying on color alone:

- appointments use the existing calendar-clock marker;
- jobs use a wrench plus a persistent left accent rail;
- the accessible name begins with “Appointment” or “Job”;
- status colors keep their existing product meaning rather than becoming the only type signal.

The first glance is the visible range and mixed schedule. The second glance is the workspace-wide unscheduled queue for dispatchers. New appointment remains the primary action; New job appears beside it only for `jobs:write` callers.

## Layout and responsive behavior

- **Desktop month:** Seven aligned day columns, compact one-line chips, and a right rail for Today, Unscheduled, Upcoming, and range totals.
- **Desktop week:** Seven tall day columns. Chips stack compact time above a two-line title so narrow columns do not erase the work name.
- **Phone week:** A single-column agenda grouped by non-empty day. It includes customer detail and replaces the unusable seven-column grid.
- **Phone month:** The existing bounded month grid remains horizontally contained; week is the recommended field-worker agenda.
- **Actions and filters:** Wrap rather than overflow. Restricted callers never see New job, Unscheduled, or Only mine because their API result is already scoped.

## Reused primitives

- `Card`, `Button`, `Badge`, `Switch`, `ScrollArea`
- `PageLoadingState`, `PageErrorState`
- `AppointmentDetailsDialog`, `JobDetailDialog`
- `NewAppointmentDialog`, `NewJobDialog`
- `LocationFilter`
- project date utilities, query keys, capability matrix, and status palettes

## States and interaction

- Combined loading waits for both required schedule sources.
- Either required source error renders one retry surface for both queries.
- Empty month/week, Today, Upcoming, and Unscheduled states use explicit copy.
- Every entry is a native button with hover, `focus-visible`, tooltip, and a complete accessible name.
- Month overflow exposes a real “+N more” button; expanded state resets when range or view changes.
- Motion is color-only and disabled by `motion-reduce`.
- Deep-linked `?job=<id>` entries fetch directly and open the existing job dialog.

## Production checks

- Server-side role scoping on list and detail routes.
- Type signal is icon/rail/text, not color alone.
- Native controls and visible keyboard focus.
- Mobile agenda prevents seven-column reflow failure.
- No new emoji, gradients, hover lift, `transition-all`, fabricated claims, or external assets.
- Team’s Booking calendar toggle enables a shared booking resource; assigned appointments carry that staff id and appear on the linked login’s calendar.
- Automated frontend tests cover both species, both dialogs, dispatch gating, queue independence, deep links, and personal filtering.
- Desktop month/week, dispatcher/technician, and narrow agenda captured under `.ezcoder/eyes/out/` during implementation.
