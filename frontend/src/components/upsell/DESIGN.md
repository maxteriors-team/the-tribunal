# On-site upsell — design read

The technician-facing surface for the scoped upsell API
(`/api/v1/workspaces/{id}/upsell/*`). Backend authz notes live in
`backend/app/core/permissions.py`; this document covers the UI only.

## Design read

- **Surface:** Application UI, phone-first. Leads as a task tool; borrows nothing
  from the dashboard archetype because there is no data to compare — there is one
  decision and one action.
- **Audience:** A field technician on the `field` tier. Not a CRM user: they wash
  houses and hang lights. They have never seen the pipeline, and by design never
  will. Outdoors, bright sun, one hand, gloves on, possibly weak signal.
- **Single job:** Turn _"this yard would look great with path lights"_ into a sent
  proposal before the technician leaves the driveway — hardware, a recurring Care
  Plan, or both.
- **Task and risk:** A few times a week per tech, so nothing may rely on
  memorised affordances. Building a draft is cheap and reversible. **Sending is
  not** — a real customer receives it — so send is the one action behind a
  confirm step, and the confirm step names the person and the number.
- **Content:** A short job list, one customer, a handful of add-ons, a running
  total. Longest plausible values: catalog names like "Landscape lighting install
  — transformer included" and 5-figure totals. Both must wrap without breaking
  the row.
- **Platform:** Next.js dashboard. Field techs are redirected to an operational
  allowlist (`FIELD_OPERATIONAL_PREFIXES`), so `/upsell` had to be added there or
  the feature is literally unreachable for its only audience.
- **Constraints:** Reuse the local shadcn-derived primitives, `lucide-react`,
  existing tokens, `queryKeys`, `page-state`, and `formatCurrency`. No new deps.

## Evidence

Archetype: **Application UI** (7/74 documents; focus mentioned in 7/7, disabled
state 6/7 — small sample, treated as direction rather than house style).
**Mobile/native coverage in the corpus is 0/74**, so phone behaviour comes from
platform convention and rendered device-width testing, not corpus frequency.

- Aligned: `linear.app` — predictable control placement and fast state
  recognition, which is what a twice-a-week user needs most.
- Aligned: `superhuman` — a single obvious next action per screen; the technician
  should never choose between two comparably-weighted buttons.
- Contrast: `intercom` — richer, more conversational surface. Rejected here: this
  screen is transactional and ends, it does not host an ongoing thread.

Local product evidence outranked all of the above where they disagreed: the page
frame, spacing rhythm, and state components come from `today-page.tsx`.

## Thesis

**A receipt being written at the customer's door.**

The screen is a running tally: pick the house, tap add-ons, watch the total grow,
send. The device is the **pinned summary bar** — total and primary action fixed
in the thumb zone, always visible while the menu scrolls behind it. It belongs
because this is a point-of-sale interaction conducted standing up: the number is
the thing under negotiation, and a technician quoting a price out loud must be
able to read it without scrolling. It is not decoration; hiding it would make the
screen worse.

- **First glance:** whose house, and what is the total.
- **Second glance:** which add-ons are on the list.
- **Primary action:** the pinned bar. Exactly one per step.

**One-time money and recurring money never merge.** Hardware totals and a Care
Plan's yearly price sit on separate lines in the summary bar, the draft, and the
send confirmation. Summing them would state a number the customer never agreed
to, and every Care Plan price carries an explicit `/yr`.

Composition is a single 640px content rail, shared by the header, list, and the
inner content of the pinned bar so their edges align at every breakpoint.

**Semantic roles.** Neutral surfaces throughout; the product accent marks
_selection only_, because selection is the one piece of state the technician is
actively manipulating. Money is `tabular-nums` so the total does not shift
horizontally as it changes. No semantic tint-on-tint: a selected row is a
neutral surface with an accent border and a check, not a wash of accent at 10%.

**Motion.** Border, background, and icon colour transitions at the token
duration, named properties only. The stepper and total do not animate position.
Reduced motion removes transitions, and nothing depends on them for meaning.

## Care Plan section

Sits below the add-on list and is **hidden entirely** when the workspace
configures no tiers — not every trade sells maintenance, and a dead section is
worse than no section. Two things separate it from the list above it:

1. **Its price is a function of an input the technician gathers.** Plans price as
   `base + per_fixture × (count − free)`, so the fixture count is a pricing field
   and sits _above_ the tiers: a number that moves under your thumb after you
   have read it aloud is worse than one you set first. Previous prices stay on
   screen while a new count is priced so the list never blanks out mid-count.
2. **It is billed yearly.** Re-tapping the selected tier clears it, so a
   technician who opened the plan to read a price aloud can get back to "no plan"
   without restarting the proposal.

## States planned

Loading, error + retry, three distinct empty states (no jobs assigned, no add-ons
configured, none matching the job), selection empty, submitting, created,
send-confirm, send failure with the draft preserved, and offline/failed mutation.
The catalog list is keyboard operable, every control has a visible focus ring,
and the pinned bar is a real `<button>` inside a labelled region.

## Accessibility

WCAG 2.2 AA is the floor. Specifics carried by this screen: the quantity stepper
is a labelled group with per-item accessible names ("Add one Landscape lighting
install"); selection state is conveyed by `aria-pressed`, not colour alone; the
running total is an `aria-live="polite"` region so a screen-reader user hears it
change; the send confirmation traps focus and names the recipient; touch targets
are ≥44px; the pinned bar reserves safe-area inset for notched devices.
