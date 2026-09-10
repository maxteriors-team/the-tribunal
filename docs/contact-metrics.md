# Contact metrics: F10–F12

Implements the contact-reporting findings in [the CRM audit](audits/2026-09-09-crm-ux-reporting-audit.md).

## Conversion time and the interim report

A **new-client conversion** means a contact's **first transition into `converted`**. A period conversion report must count that event's timestamp in `[start, end)`, regardless of when the lead was created. A lead created 75 days ago and first converted today belongs in today's conversion period.

The current contact model has no conversion timestamp or complete, trustworthy status-event history. `created_at` is not conversion time; `updated_at` also changes for unrelated edits. Current AI facts, opportunity wins and import timestamps do not establish a complete contact conversion history. **No period-conversion metric is presented until that history can support it.**

The interim cards are explicitly labelled **Converted contacts — Created in past 30 days / Created year to date**. They count contacts **currently** converted whose **creation** dates fall within the displayed window. The 75-day-old lead is correctly absent from the 30-day *creation cohort*, not falsely reported as zero conversion activity. Copy beside the cards discloses the distinction and unavailable history.

The API preserves the legacy `new_clients_30d`, `new_clients_change`, and `total_new_clients_ytd` field names for compatibility, but declares `client_metric_basis = "creation_cohort_current_status"` and documents those semantics in OpenAPI. Consumers must not label them conversions during the period.

### History and reconversion limits

- Reverting a contact out of `converted` removes it from the current-status snapshot; changing it back restores one contact, not another new client. Prior creation-cohort counts can therefore change retroactively.
- The interim report cannot distinguish first conversions from reconversions, establish conversion dates, or reconstruct an as-of historical status.
- Future first-conversion tracking must cover every status writer and preserve unknown historical dates. Do not backfill conversion time from contact creation, last modification, or migration time.
- Counting **conversion events**, including reconversions, would require append-only status history and a separately labelled event metric. That is not the definition of a new client.

## Windows and drill-downs

Stats are **workspace-wide**, independent of the contact list's search and filters. The trailing window is 30 elapsed days ending at the response's `period_end`; its comparison is the immediately preceding 30 days. All windows include the start and exclude the end. Future-dated contacts are excluded.

YTD begins at January 1 midnight in the workspace's reporting timezone, using the existing reporting-timezone fallback policy. The API returns `timezone` and exact UTC `period_start`, `period_end`, and `year_start` bounds. Each card's **View contacts** action replaces prior search/status/advanced filters with these same bounds (and `status = converted` where appropriate), resetting pagination. Later status edits may change a drill-down because these are live snapshots, not persisted historical reports.

JSON date comparisons are parsed into datetime query parameters in the shared filter engine; malformed dates produce a validation error rather than dropping the predicate. Offset-free dates use UTC for timezone-aware columns. The card always sends offset-bearing server bounds.

## Status counts

The list response includes server-aggregated `status_counts`. Every count, including **All**, uses the same workspace, search, tags, simple filters and advanced rules. These counts exclude the separate selected **status tab**, sort order, page and page size. An explicit advanced status rule still belongs to the filter scope.

`total` continues to count the selected-status result for pagination. With 100 new contacts and one qualified contact on the next page, badges show **All 101 / New 100 / Qualified 1**. Selecting Qualified makes the result total 1 but leaves those badge counts unchanged. Missing/loading/error counts are shown as unavailable, not fabricated zeros.

## Zero baseline

When the prior cohort is zero, percentage change is mathematically undefined, including 0 → 0. The API sends `null`; the UI shows neutral **No baseline**, with no percentage or trend arrow. Nonzero baselines retain signed percentages, including a genuine −100% drop to zero.

## Data and contract safety

No ORM/table/schema migration or historical backfill is made. Existing contact data is untouched. Only response contracts change; regenerate `backend/openapi.json` and `frontend/src/lib/api/_generated.ts` together. Regression coverage includes the 75-day-old conversion, reconversion snapshot behavior, exact date/timezone boundaries and drill-downs, 101-contact/off-page facets, filtered scope and workspace isolation, and zero baselines.

## Local verification — 2026-09-10

- **133 backend tests passed:** contact stats/validation routes, PostgreSQL contact-query tests, and shared filter tests.
- **43 frontend tests passed:** contact components and the contact API client. Frontend typecheck and targeted ESLint passed.
- **Backend checks passed:** targeted Ruff and mypy on the changed application modules.
- **Seven HTTP probes passed:** real auth, contact routes, and PostgreSQL on an isolated loopback server. Verified cohort metadata/null growth, off-page counts, unchanged All, exact drill-down, malformed-date 400, unauthenticated 401, and cross-workspace 403. Synthetic data lived in one rolled-back transaction; no background workers started.
- **Contracts regenerated:** OpenAPI and generated TypeScript were byte-identical on repeat generation. `ci.codegen`'s comparison against HEAD remains nonzero with these intentionally uncommitted artifacts; that check was not weakened.

No full release CI, production deployment, or visual browser review was performed. No commit or deployment was made for this task.