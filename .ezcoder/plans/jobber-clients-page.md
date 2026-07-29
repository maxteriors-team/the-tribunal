# Replicate the Jobber Clients page on our Contacts page

Make `/contacts` match the Jobber Clients page from the reference screenshot: a
stat-cards row on top, a "Filtered … (N results)" heading, a filter bar (chips
left / search right), and a **table** list (checkbox · Name · Address · Tags ·
Status · Last Activity) with sortable Name and Last Activity columns — replacing
today's card grid.

## Reference anatomy (Jobber)

1. **Header**: page title + primary green **New Client** button + secondary
   **More Actions** (•••) button.
2. **Stat cards row** (4 across): "New leads / Past 30 days / 52 / ↑24%",
   "New clients / Past 30 days / 5 / ↑400%", "Total new clients / Year to date /
   1618", and a promo card ("How can you be more efficient?").
3. **"Filtered clients (1,774 results)"** section heading.
4. **Filter bar**: `Filter by tag +` chip, `Status | Leads and Active` chip
   (left), `Search clients…` box (right).
5. **Table**: columns `☑ | Name ↕ | Address | Tags | Status | Last Activity ↕`.
   Rows = bold name, multi-line address, tag pills, colored status dot + label,
   relative last-activity ("3:28 PM", "Mon", "Yesterday").

## Mapping decisions (our domain)

- **Nouns**: keep our term **"Contacts"** (matches the sidebar + route
  `/contacts`); replicate layout/behavior, not the literal word "Clients".
  Primary button stays **"Add Contact"**; **More Actions** menu holds Import
  CSV + Select (bulk mode).
- **Statuses**: we have 5 (`new`, `contacted`, `qualified`, `converted`,
  `lost`) vs Jobber's Lead/Active. Render each as a **colored dot + label**
  using existing `contactStatusDotColors` + `contactStatusLabels`. Keep the
  existing status filter (all + 5 statuses) but restyle it into the filter bar.
- **Stat cards** (3 metric + 1 promo). Metric definitions (workspace-scoped,
  UTC windows), computed from `Contact.created_at` / `Contact.status`:
  - **New leads — Past 30 days** = contacts created in the last 30 days.
    Change % vs the prior 30-day window.
  - **New clients — Past 30 days** = contacts with `status='converted'` created
    in the last 30 days. Change % vs the prior window.
  - **Total new clients — Year to date** = `status='converted'` created since
    Jan 1 (current year). No change badge (matches Jobber).
  - **Promo card** = static "Put follow-up on autopilot" card linking to
    `/automations` (mirrors Jobber's efficiency promo; not data-driven).
  - Change is returned **preformatted** (`"+24%"`, `"-10%"`, `"+0%"`) so the
    existing `isTrendUp()` util in `components/dashboard/animations.tsx` works.
- **Last Activity** value = `last_message_at ?? updated_at`, formatted Jobber
  style (today → time, yesterday → "Yesterday", ≤7d → weekday, else → "MMM d").
- **Sorting**: two sortable columns. Add sort keys `name_asc`, `name_desc`,
  `last_activity_asc`, `last_activity_desc` to the backend; default page sort
  becomes `last_activity_desc` (mirrors Jobber's `sort=UPDATED_AT DESC`).
  Existing `created_at` / `last_conversation` / `unread_first` keys stay.

## Backend changes

- `backend/app/schemas/contact.py`: add `ContactStatsResponse` (BaseModel):
  `new_leads_30d: int`, `new_leads_change: str`, `new_clients_30d: int`,
  `new_clients_change: str`, `total_new_clients_ytd: int`.
- `backend/app/services/contacts/query_service.py`: add
  `async def get_stats(self, *, workspace_id) -> dict` running workspace-scoped
  `COUNT` queries for the 5 windows (leads 30d + prev 30d, clients 30d + prev
  30d, clients YTD), applying `apply_workspace_scope`, and formatting the two
  change strings via a small `_pct_change(curr, prev)` helper
  ("+N%"/"-N%"/"+0%"; when prev == 0 and curr > 0 → "+100%", when both 0 →
  "+0%"). Use `datetime.now(UTC)` windows.
- `backend/app/api/v1/contacts.py`: add
  `@router.get("/stats", response_model=ContactStatsResponse)` gated by
  `CanReadCRM`, **registered before** the `/{contact_id}` route (place it right
  after the `/ids` route at line ~123 so the static path wins over the param
  route). Delegate to `ContactQueryService(db).get_stats(...)`.
- `backend/app/services/contacts/contact_repository.py`: extend the `sort_by`
  branch (around lines 114–129) with:
  - `name_asc` → `order_by(Contact.first_name.asc(), Contact.last_name.asc(), Contact.id.desc())`
  - `name_desc` → same fields `.desc()`
  - `last_activity_asc` / `last_activity_desc` →
    `conv_subquery.c.max_message_at` asc/desc `nullslast()`, then `Contact.id.desc()`.
  Update the docstring listing valid sorts.
- Backend tests: add `backend/tests` coverage for the stats endpoint (counts +
  change formatting) and for the new sort keys returning 200 with expected order.

## Codegen (contract sync)

- Run `make codegen` (or `make ci.codegen`) to regenerate `backend/openapi.json`
  and `frontend/src/lib/api/_generated.ts`; commit both in the same commit as
  the backend change (per CLAUDE.md release rules).

## Frontend changes

- `frontend/src/lib/api/contacts.ts`: add `ContactStatsResponse =
  Schemas["ContactStatsResponse"]`; add sort keys to `ContactSortBy`; add
  `contactsApi.getStats(workspaceId)` calling
  `GET /api/v1/workspaces/{workspace_id}/contacts/stats`.
- `frontend/src/lib/query-keys.ts`: add `contacts.stats(workspaceId)`.
- `frontend/src/hooks/useContacts.ts`: add `useContactStats(workspaceId)`
  (React Query, `enabled: !!workspaceId`).
- **New** `frontend/src/components/contacts/contacts-stats-cards.tsx`: renders
  the 4-card row (3 metric cards + promo) using `Card`/`CardHeader`/`CardContent`
  + trend badge (reuse `isTrendUp`), with a skeleton state. Grid
  `md:grid-cols-2 lg:grid-cols-4`.
- **New** `frontend/src/components/contacts/contacts-table.tsx`: table built on
  `components/ui/table` primitives. Header: select-all checkbox, Name (sortable
  button + arrow), Address, Tags, Status, Last Activity (sortable). Rows:
  per-row checkbox (selection mode), name (bold, links to `/contacts/{id}`),
  formatted address (from `address_line1/line2/city/state/zip`), tag pills via
  `TagBadge` (max 3 + "+N"), status dot+label, relative last activity. Include a
  `ContactsTableSkeleton`. Add a local `formatLastActivity()` helper (today →
  `formatTime`, yesterday → "Yesterday", ≤7d → `format(d,"EEE")`, else
  `formatDayMonth`) and a `formatContactAddress()` helper.
- **New** `frontend/src/components/contacts/contacts-filter-bar.tsx` (or refactor
  `contacts-toolbar.tsx`): one row — status segmented control + advanced-filter
  trigger (existing `ContactFilterBuilder`) on the left, search input on the
  right, matching the Jobber chip/search layout.
- `frontend/src/components/contacts/contacts-page.tsx`: recompose to
  header (title + count + **Add Contact** + **More Actions** dropdown) →
  `<ContactsStatsCards/>` → "Filtered contacts (N results)" heading →
  `<ContactsFilterBar/>` → `<ContactsTable/>` → pagination. Preserve all
  existing wiring (selection/bulk actions, select-all-matching, create/import/
  bulk-tag/delete dialogs, capability gating). Swap the card grid for the table;
  move Import CSV + Select into the More Actions menu; default `sortBy` to
  `last_activity_desc`.
- Leave `contact-card.tsx`, `contacts-list.tsx`, `contacts-toolbar.tsx` files in
  place (used by the contact detail split view / not deleted) unless refactor
  cleanly subsumes the toolbar.

## Verification

- `.ezcoder/eyes/http.sh http://localhost:8000/api/v1/workspaces/<id>/contacts/stats -H "Authorization: Bearer <token>"`
  → confirm 200 + the 5 fields; hit `…/contacts?sort_by=name_asc` and
  `…?sort_by=last_activity_desc` → confirm 200 + ordering.
- `make ci.codegen` clean (no drift), `make ci.backend`, `make ci.frontend`.
- Visual check `/contacts` at desktop width: header, 4 cards, table columns,
  sortable arrows, status dots, selection + bulk bar, pagination.

## Risks / notes

- Route ordering: `/stats` MUST precede `/{contact_id}` or FastAPI treats
  "stats" as a contact id → 422/404.
- Live production CRM data — this is read-only additive (new endpoint + sort
  keys); no migration, no schema change to `contacts` table.
- `converted` is our proxy for "client"; if the team wants a different
  lead→client definition, only `get_stats` needs adjusting.
- Changing default sort to `last_activity_desc` changes initial ordering for all
  users (intended, matches Jobber).

## Steps

1. Add `ContactStatsResponse` to `backend/app/schemas/contact.py`.
2. Add `get_stats()` + `_pct_change()` to `backend/app/services/contacts/query_service.py` with workspace-scoped COUNT queries for the 5 windows.
3. Add the `GET /stats` route (CanReadCRM) to `backend/app/api/v1/contacts.py`, placed before the `/{contact_id}` route.
4. Add `name_asc`/`name_desc`/`last_activity_asc`/`last_activity_desc` sort branches (and docstring) to `backend/app/services/contacts/contact_repository.py`.
5. Add backend tests for the stats endpoint and the new sort keys.
6. Run `make codegen`; commit regenerated `backend/openapi.json` + `frontend/src/lib/api/_generated.ts`.
7. Extend `frontend/src/lib/api/contacts.ts` with `ContactStatsResponse`, new `ContactSortBy` keys, and `contactsApi.getStats()`.
8. Add `contacts.stats()` to `frontend/src/lib/query-keys.ts` and `useContactStats()` to `frontend/src/hooks/useContacts.ts`.
9. Build `frontend/src/components/contacts/contacts-stats-cards.tsx` (3 metric cards + promo + skeleton).
10. Build `frontend/src/components/contacts/contacts-table.tsx` (columns, sortable headers, selection, row link, address/last-activity helpers, skeleton).
11. Build `frontend/src/components/contacts/contacts-filter-bar.tsx` (status segmented + advanced filter + right-aligned search).
12. Recompose `frontend/src/components/contacts/contacts-page.tsx` to header + stats cards + results heading + filter bar + table + pagination, preserving all existing selection/dialog wiring and defaulting sort to `last_activity_desc`.
13. Verify with `.ezcoder/eyes/http.sh` (stats + sort endpoints), then run `make ci.codegen`, `make ci.backend`, `make ci.frontend`; fix any failures.
