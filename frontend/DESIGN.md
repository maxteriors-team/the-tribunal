# Frontend design notes

Living notes for the operator-facing UI. Add a section when a surface's layout
rules are non-obvious from the components alone.

## Contact console + contact detail (Jul 2026)

### Design read

- **Surface:** dense application UI (CRM operator console), dark-first theme.
- **Audience:** home-service owners and dispatchers triaging leads on desktop,
  checking a contact between jobs on a phone.
- **Single job:** the conversation page makes replying easy with contact context
  one glance away; the detail page answers "who is this and what has happened?".
- **Content extremes:** long mailing addresses, long agent names, message bodies
  of arbitrary length, contacts with zero activity.

### Thesis

Every pane is a bounded column. Content wraps or truncates _inside_ its rail, and
the contact record gets a full-width home where its facts and history can breathe
instead of fighting the conversation for horizontal space.

### Layout rules

- `ScrollArea` (`components/ui/scroll-area.tsx`) forces the Radix viewport's
  injected wrapper back to `display: block; width: 100%`. Radix ships it as
  `display: table`, which shrink-to-fits to the content's max-content width — in
  a fixed rail that pushes long values past the column, where `overflow-hidden`
  clips them. This is why quick actions, addresses and badges used to disappear
  off the right edge.
- The conversation console (`components/layout/conversation-layout.tsx`) renders
  three columns only at ≥1280px: `minmax(280px,320px) minmax(0,1fr) minmax(300px,340px)`.
  `minmax(0, 1fr)` is load-bearing; a bare `1fr` floors at the message column's
  max-content width and shoves the contact rail off screen.
- Below 1280px the rails become slide-overs (`Sheet`) triggered from a compact
  bar above the conversation. Sheets own their close control and carry an
  `sr-only` `SheetTitle`/`SheetDescription` for an accessible name.
- Rail values truncate with the full string in `title`; roomy layouts pass
  `wrapValues` to `ContactInfoSection` so addresses show in full.
- Breadcrumbs in the app header collapse ancestors below `sm` and truncate the
  current page, so deep routes such as `/contacts/123/details` never wrap the
  header on a phone.

### Contact detail page

Route: `/contacts/[id]/details` → `components/contacts/contact-detail/`.

- Identity card (avatar, status, engagement, last engaged) with Message, Call,
  Schedule and Edit. Message returns to the conversation; Call reuses
  `callContact` from `use-contact-sidebar-data`, so the rail and the page fail
  the same way when no voice-enabled number exists.
- Left column reuses the rail sections (`ContactInfoSection`,
  `ImportantDatesSection`, `ContactNotesMeta`, `EngagementSummary`,
  `ContactFilesMedia`) so both surfaces stay in sync.
- Right column is `ContactHistory`: messages, calls, appointments and quotes
  merged by `lib/contacts/contact-history.ts` into one reverse-chronological
  record, grouped by day, with future-dated bookings hoisted into an "Upcoming"
  section that shows the date, not just a time. Filters are `aria-pressed`
  buttons with counts, matching the contacts filter bar's segmented control.
- No new endpoints: it composes `GET /contacts/{id}/timeline`, the appointments
  list and the quotes list, all through shared hooks in `hooks/useContactRecords.ts`
  so the cache is shared with the rail.

### States covered

Loading skeletons, request error with retry, no-activity empty state,
filtered-empty state, contact-not-found (`notFound()`), and the narrow/mobile
stacked layout.
