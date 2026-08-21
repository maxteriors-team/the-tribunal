# Time & Attendance design note

## Design read

- **Surface:** authenticated operations dashboard with a data-dense admin review mode.
- **Audience:** staff clocking shifts from phone or desktop, and payroll admins reviewing a pay-period window.
- **Single job:** make the correct next action obvious: clock in, pause/resume, or clock out for staff; verify/export hours and review technician activity for admins.
- **Risk:** missed taps, overlapping shifts, silent corrections, or unclear exports can change pay. State, timestamps, correction reasons, and exclusions must be explicit.
- **Constraints:** reuse the existing AppSidebar, report date picker anatomy, cards, tables, dialogs, page states, Lucide icons, capability hooks, and workspace query patterns. No new design dependency.

## Thesis

The time clock is the first-glance anchor: one status sentence, one worked-time timer, and explicit Clock in, Pause/Resume, and Clock out actions. The timer freezes while paused. Recorded shifts are the second glance. Admin-only team review stays behind a clearly labelled tab with the date range, correction actions, and payroll export in one aligned toolbar.

- Use existing neutral surfaces and typography; reserve destructive styling for voiding a record.
- Use text plus icons for every status and action. Never communicate open/complete/void by colour alone.
- Keep timestamps and durations tabular. Display the workspace timezone beside the range.
- On narrow screens, shift rows become labelled cards; actions remain native buttons with visible focus.
- Loading, empty, error, retry, mutation-pending, open-shift, paused-shift, and export-exclusion states are explicit.
- UI copy states that the product records timestamps only, does not track location/activity, and separates gross/paused/worked hours without deciding whether a pause is paid.

## Trust and accessibility contract

- Every input has a persistent label; correction and void reasons are required and described.
- Clock state changes announce through existing toasts and refreshed status text.
- Dialog focus is managed by the existing Radix primitives; no pointer-only action is introduced.
- Tables retain semantic headers on desktop; mobile cards retain the same labels and action order.
- Open and void entries are visibly excluded from payroll export; completed rows expose worked and paused time separately.
- Employee self-service exposes only the signed-in user's records; team data and exports are admin-only in both UI and API.

## Technician scorecard

- Reuse the existing scorecard range controls and cards; owners/admins switch between **AI receptionist** and **Technicians**.
- Show direct operational counts only: assigned jobs, completed job-time records, job time, attendance worked time, and paused time.
- Do not synthesize a score, rank workers, or imply quality, pay, productivity, or customer satisfaction from unlike records.
- Keep the route and API behind `reports:view`; field technicians retain self-only attendance without seeing team scorecards.
- Technician cards reflow from five compact metrics to a two-column mobile layout without horizontal scrolling.

## Verification boundary

Authenticated Playwright passed two desktop/mobile scenarios at 1366×900 and 390×844, covering pause/resume with a frozen timer, clock-out, admin team visibility, audited note correction, payroll download, populated technician scorecards, restricted navigation, horizontal overflow, and serious/critical Axe checks. Frontend CI also passed lint, TypeScript, 1,421 component/unit tests, and the production build. Screenshots and CSV evidence are under `.ezcoder/eyes/out/attendance/`. Automated checks do not replace a manual screen-reader, keyboard-only, zoom/reflow, or legal review; no accessibility-conformance claim is made.
