# Ad Library Prospecting — Full Feature Plan

Pull advertisers from public ad libraries (Meta Ad Library first, Google Ads
Transparency second), detect the ones who are **consistently running ads but
NOT iterating creatives** (long-running same ads, few distinct creatives, low
refresh cadence), trace + enrich their contact info, and ingest qualified
advertisers into the CRM as prospects → contacts → outreach.

This is the "people who already spend on ads and clearly need help running
better ads" prospecting engine.

---

## 1. What already exists (reuse, do not rebuild)

The repo already has a **source-agnostic lead-discovery + outbound-mission
framework**. This feature plugs into it instead of inventing a parallel stack.

- **Models**: `OutboundMission` (`backend/app/models/outbound_mission.py`),
  `LeadDiscoveryJob` + `DiscoverySourceType` enum
  (`backend/app/models/lead_discovery_job.py`), `LeadProspect` +
  `LeadEnrichmentResult` (`backend/app/models/lead_prospect.py`),
  `OutboundSequence`/enrollment, `WorkspaceIntegration` (encrypted per-workspace
  credentials, `backend/app/models/workspace.py:144`).
- **Discovery provider abstraction**: `LeadDiscoveryProvider` protocol +
  `BaseLeadDiscoveryProvider` (`backend/app/services/lead_discovery/protocol.py`),
  normalized `RawLead`/`LeadDiscoveryRequest`/`ProviderResult`
  (`.../types.py`), `dedupe.py`, and a reference impl
  `GooglePlacesLeadProvider` (`.../providers/google_places.py`).
- **Scraping/enrichment**: `WebsiteScraperService`
  (`backend/app/services/scraping/website_scraper.py` — already detects meta/
  google/tiktok ad pixels + social links), `enrich_contact_data`
  (`.../enrichment_service.py`), `AIContentAnalyzerService`, `lead_scorer.py`,
  `google_places.py`.
- **Mission API/service**: `OutboundMissionService`
  (`backend/app/services/outbound/mission_service.py`) + router
  (`backend/app/api/v1/outbound_missions.py`) already does mission CRUD,
  prospect listing, discovery-job listing, enrichment-status aggregation,
  sequence overview, enrollments.
- **Worker framework**: `WorkerSpec`/`WorkerRegistry`/`start_all_workers`
  (`backend/app/workers/__init__.py`), `RetryableWorker`/`BaseWorker`
  (`backend/app/workers/base.py`, `retryable.py`), existing `enrichment_worker`.
- **Frontend conventions**: query-key factory (`frontend/src/lib/query-keys.ts`),
  generated API types (`frontend/src/lib/api/_generated.ts` from
  `backend/openapi.json`), `find-leads` / `find-leads-ai` routes as UI precedent.

### Gaps this feature must close (not built yet)
1. **No job-runner**: nothing actually executes a `LeadDiscoveryJob` through a
   provider and persists `LeadProspect` rows (grep for `run_discovery` /
   `lead_miner` → no matches).
2. **No prospect enrichment worker**: `enrichment_worker` enriches `Contact`
   rows, not `LeadProspect`.
3. **No prospect → Contact promotion** anywhere.
4. **No ad-library provider** and **no ad-signal analysis**.
5. **No frontend** for missions/prospects/ad-library (frontend grep for
   `mission|prospect|discovery` → none).

So this feature builds: ad-library providers, an ad data model + signal engine,
the discovery/enrichment/promotion orchestration that was always missing, the
API, and the UI.

---

## 2. External grounding (researched, working references)

Meta Ad Library API constraints (verified against `facebook.com/ads/library/api`
and 2026 practitioner guides):

- Endpoint `GET https://graph.facebook.com/v22.0/ads_archive` (bump version
  ~annually; v17 and earlier already error). Auth = `access_token` (a Meta
  developer app token; `ads_read`). The Ad Library is public data.
- `ad_reached_countries` is **mandatory**; one country set per call.
- **Commercial ads** return metadata (page, creatives, delivery start/stop,
  active status, platforms, snapshot URL) but **no spend/impressions** (those
  are political-only). EU commercial coverage is strong post-DSA; **US/non-EU
  commercial returns can be incomplete vs the web UI** — this is why we add a
  pluggable third-party provider as a fallback.
- Practical gotchas (from `krusemediallc/Meta-Ads-Spy-Claude-Code-Airtable`
  `META_ADS_LIBRARY_API.md`, updated 2026-04): date range
  (`ad_delivery_date_min/max`) effectively required; requesting
  `ad_creative_bodies` **with pagination** intermittently 500s → use minimal
  fields on list calls and fetch creative fields per-ad; `ad_snapshot_url` is
  the only path to actual creative media (render in a headless browser); default
  tier ≈ **200 calls/hour/app**, 429s carry `Retry-After`; the snapshot URL
  embeds the token (never log it). `sort_by=longest_running` is a supported
  server sort — directly useful for our ICP.

Key insight for our ICP signal: **the exact "long-running / few creatives / no
testing but consistent" signal is computable from the FREE official API
metadata** (`ad_delivery_start_time`, `ad_delivery_stop_time`,
`ad_active_status`, creative bodies/links) for commercial ads — we do **not**
need spend/impressions. Third-party providers only improve coverage/volume.

Reference repos (read for patterns, MIT/public):
- `krusemediallc/Meta-Ads-Spy-Claude-Code-Airtable` — recent, production-shaped:
  `/ads_archive` request, `resolve_page_id()`, two-phase list→per-ad creative,
  rate-limit/Retry-After handling, Selenium snapshot extraction.
- `minimaxir/facebook-ad-library-scraper` — canonical official-API field list.
- `RamsesAguirre777/facebook-ads-library-mcp` — `/ads_archive` field set +
  crawl4ai snapshot rendering, MCP tool shapes.
- `faniAhmed/GoogleAdsTransparencyScraper` — Google Ads Transparency Center
  scraping approach (no official API exists; alt = SerpApi's Google Ads
  Transparency endpoint).

Third-party fallback options to support behind one interface (config-gated, no
hard dependency): Apify "Facebook Ad Library Scraper" actor, ScrapeCreators API,
SerpApi. Each gives fuller US-commercial coverage without Meta app review.

**Compliance**: prefer the official API and licensed third-party APIs over raw
scraping; Meta ToS restricts scraping (cf. Meta v. Bright Data). Snapshot
rendering and any scraper path get rate-limited, robots-aware, and ToS-flagged.
All discovered emails/phones are PII → encrypted at rest (already the
`LeadProspect`/`Contact` pattern) and run through existing suppression/opt-out.

---

## 3. Target architecture

```
Ad library (Meta / Google)                Existing CRM rails
        │                                         │
        ▼                                         │
[Ad-intelligence providers] ── normalized ──► [AdAdvertiser + AdCreative tables]
  MetaAdLibraryProvider                              │  (track ads over time)
  MetaThirdPartyProvider (fallback)                  ▼
  GoogleAdsTransparencyProvider              [Signal engine] → opportunity score
        ▲                                          │  (long-run, low-diversity,
        │ (re-scan monitor worker)                 │   low-refresh, continuous)
        │                                          ▼ ICP-qualified
[AdLibraryDiscoveryWorker] ── creates ──►   [LeadProspect]  (existing model)
                                                   │
                            [contact tracing + ProspectEnrichmentWorker]
                                                   │  landing domain + FB page
                                                   ▼  about → website_scraper
                                          [Promotion service] → Contact
                                                   │  + tags + business_intel
                                                   ▼  + Opportunity
                                   [OutboundMission sequence enrollment] (existing)
```

New backend package: `backend/app/services/ad_intelligence/` (providers, signal
engine, upsert, contact tracing). New models: `ad_advertiser.py`,
`ad_creative.py`. New workers: `ad_library_discovery_worker`,
`ad_monitor_worker`, `prospect_enrichment_worker`, `prospect_promotion_worker`.
New API router: `backend/app/api/v1/ad_library.py`. New frontend section under
`frontend/src/app/find-leads/ad-library/` + `frontend/src/components/ad-library/`.

### ICP signal definition (the product differentiator)
Per advertiser (one `page_id`/domain), over a rolling window (default 365d):
- `longest_running_active_days` = max(now − `ad_delivery_start_time`) over
  currently-active ads. High = stale winner they never refresh.
- `active_creative_count` / `distinct_creative_count` (dedupe by normalized
  body+link+media hash). Low = few creatives.
- `creative_refresh_rate` = distinct new creatives introduced per 30d. Low = no
  testing.
- `continuity_score` = fraction of weeks in window with ≥1 active ad. High =
  consistent spender.
- `platform_spread`, `media_mix` (image/video/carousel) for context.
- **`opportunity_score`** = weighted blend that rewards
  `high continuity + long longest-run + low distinct-creative + low refresh`
  and stores a human-readable `reasons[]` (evidence) e.g.
  "Running the same 2 creatives for 214 days, 0 new creatives in 90 days".
- Thresholds are workspace-configurable (a saved "ICP profile").

---

## 4. Key decisions / open questions (surface before/with build)
- **Provider default**: ship official Meta API first (free, covers the signal).
  Third-party providers are config-gated adapters, off by default. OK?
- **Credentials**: store Meta token per-workspace via `WorkspaceIntegration`
  (`integration_type="meta_ad_library"`), with a global `settings` fallback for
  single-tenant/dev. Matches existing integrations pattern.
- **Snapshot media**: rendering creatives via headless browser (Selenium/
  Playwright) is optional/Phase-2 — the signal + outreach don't need the image,
  only metadata. Recommend gating it behind a flag to avoid a heavy browser dep
  in the API process.
- **Google Ads Transparency**: no official API → SerpApi adapter is the lowest-
  risk path; raw scraping is the fallback. Lower priority than Meta.
- **Scale/worker model**: per CLAUDE.md, workers run in the single backend
  process; the discovery/monitor workers must be poll-based + `skip_locked` and
  rate-limited so multiple replicas don't multiply Meta API calls.

---

## 5. Verification strategy
- Backend: pytest for providers (mock Graph API), signal math, upsert/dedupe,
  promotion; `make ci.backend`.
- Endpoints: `.ezcoder/eyes/http.sh` against the new `/ad_library/*` routes
  (search → job → advertisers → promote) to confirm status + schema + workspace
  scoping with no cross-tenant leakage.
- Workers: start backend into `.ezcoder/eyes/out/backend.log`, trigger a job
  with a recorded Graph API fixture, inspect logs via `.ezcoder/eyes/logs.sh`.
- Codegen: `make ci.codegen` (commit `backend/openapi.json` +
  `frontend/src/lib/api/_generated.ts`).
- Frontend: `make ci.frontend` + a Playwright e2e for the ad-library flow.
- Migrations: `make ci.migrations` + local `make migrate`, then hit `/readyz`.

---

## Steps

1. Add `META_AD_LIBRARY` and `GOOGLE_ADS_TRANSPARENCY` values to
   `DiscoverySourceType` (`backend/app/models/lead_discovery_job.py`) and
   `EnrichmentProvider`/source strings on `LeadProspect`; add config settings
   (`meta_ad_library_access_token`, default Graph API version, per-provider
   enable flags, rate-limit caps) in `backend/app/core/config.py`; register a
   `meta_ad_library` (and `google_ads_transparency`) `WorkspaceIntegration`
   credential type with masking in `backend/app/api/v1/integrations/credentials.py`.
2. Create `AdAdvertiser` and `AdCreative` SQLAlchemy models
   (`backend/app/models/ad_advertiser.py`, `ad_creative.py`): workspace-scoped,
   advertiser keyed by `(workspace_id, platform, page_id|domain)`, creatives
   keyed by `(advertiser_id, ad_external_id)`, with delivery start/stop, active
   flag, first_seen/last_seen, normalized creative hash, media type, platforms,
   landing domain, raw payload JSONB, and the computed signal columns +
   `opportunity_score`. Wire relationships to `LeadDiscoveryJob`/`LeadProspect`.
3. Generate the Alembic migration for the new tables/indexes
   (`make migrate.new m="ad advertisers and creatives"`), review it, apply with
   `make migrate`, and confirm `/readyz` is green via `.ezcoder/eyes/http.sh`.
4. Add Pydantic schemas (`backend/app/schemas/ad_advertiser.py`,
   `ad_creative.py`, `ad_library.py`): advertiser/creative responses, paginated
   lists, signal breakdown, search-request, ICP-threshold config, and
   promote-request, following the `lead_prospect`/`outbound_mission` schema style.
5. Define the ad-intelligence provider contract + normalized types in
   `backend/app/services/ad_intelligence/types.py` and `protocol.py`
   (`NormalizedAd`, `NormalizedAdvertiser`, `AdSearchRequest`, `AdProviderResult`,
   `AdIntelligenceProvider`), mirroring the `lead_discovery` protocol so it
   composes with `RawLead` downstream.
6. Implement `MetaAdLibraryProvider`
   (`backend/app/services/ad_intelligence/providers/meta_ad_library.py`):
   httpx client against `/ads_archive`, `resolve_page_id()` (vanity lookup +
   search fallback), mandatory `ad_reached_countries` + date window, two-phase
   list→per-ad creative fetch to dodge the pagination-500 bug, `sort_by`
   support, pagination, 429/`Retry-After` + `X-App-Usage` handling, token never
   logged, mapping to `NormalizedAd`/`NormalizedAdvertiser`. Unit-test with
   recorded Graph API fixtures.
7. Implement a config-gated third-party fallback provider
   (`.../providers/meta_thirdparty.py`) behind the same interface for fuller
   US-commercial coverage (adapter for Apify Facebook Ad Library actor /
   ScrapeCreators / SerpApi, selected by credential/setting), with graceful
   disable when no key is present.
8. Implement `GoogleAdsTransparencyProvider`
   (`.../providers/google_ads_transparency.py`) via a SerpApi-style adapter
   (primary) with a documented raw-scrape fallback, normalized to the same
   types; lower priority, fully behind a feature flag.
9. Implement the advertiser upsert service
   (`backend/app/services/ad_intelligence/ad_store.py`): persist provider
   results into `AdAdvertiser`/`AdCreative`, dedupe creatives by normalized
   hash, maintain first_seen/last_seen + active transitions across runs, and
   record provenance/evidence; idempotent per `(advertiser, ad_external_id)`.
10. Implement the signal engine
    (`backend/app/services/ad_intelligence/signals.py`): compute
    `longest_running_active_days`, `active/distinct_creative_count`,
    `creative_refresh_rate`, `continuity_score`, `media_mix`, and the weighted
    `opportunity_score` + human-readable `reasons[]`; persist onto `AdAdvertiser`.
    Pure-function core with thorough unit tests over fixture timelines.
11. Implement the ICP filter/threshold layer
    (`backend/app/services/ad_intelligence/icp.py`): workspace-configurable
    thresholds (min continuity, min longest-run days, max distinct creatives,
    max refresh rate) that select "consistent but not testing" advertisers, with
    sane defaults and a query helper for ranked advertiser lists.
12. Implement `AdLibraryDiscoveryWorker`
    (`backend/app/workers/ad_library_discovery_worker.py`): poll pending
    ad-library `LeadDiscoveryJob`s (`with_for_update(skip_locked=True)`), run the
    selected provider, call the upsert service + signal engine, update job
    counters/status, enforce the provider rate-limit cap; register it in
    `backend/app/workers/__init__.py` `WORKER_SPECS` with an enable setting.
13. Implement the advertiser→prospect generator
    (`backend/app/services/ad_intelligence/prospecting.py`): for ICP-qualified
    advertisers, create `LeadProspect` rows (identity facets from page/domain),
    attach signal `evidence`, and link `discovery_job_id`; dedupe against
    existing prospects via the existing `dedupe.py` keys.
14. Implement the contact-tracing service
    (`backend/app/services/ad_intelligence/contact_tracing.py`): derive landing
    URL/domain from ad creative link captions, fetch the advertiser's FB Page
    transparency/about for website/email/phone, and resolve the best website to
    enrich, returning normalized identifiers for the prospect.
15. Implement `ProspectEnrichmentWorker`
    (`backend/app/workers/prospect_enrichment_worker.py`): enrich
    `LeadProspect` rows (status `new`→`enriched`) using contact tracing +
    `enrich_contact_data` + `google_places` + an optional email-finder adapter
    (Hunter/Apollo, config-gated), writing `LeadEnrichmentResult` audit rows and
    updating `lead_score`; register the worker. (Closes the prospect-enrichment
    gap distinct from the contact `enrichment_worker`.)
16. Implement the prospect→contact promotion service + worker
    (`backend/app/services/outbound/promotion.py`,
    `backend/app/workers/prospect_promotion_worker.py`): promote qualified/
    enriched prospects into `Contact` (set `lead_prospects.contact_id`,
    `promoted_at`), copy ad evidence into `business_intel`, apply tags
    (`ad-library`, `stale-creative`, `long-runner`, `no-testing`), optionally
    open an `Opportunity`, and respect suppression/opt-out. (Closes the missing
    promotion path.)
17. Wire the re-scan monitor: implement `AdMonitorWorker`
    (`backend/app/workers/ad_monitor_worker.py`) that periodically re-queries
    tracked advertisers/saved monitors to refresh active/stop times and
    recompute signals (this is what proves "still running the same ad over
    time"), with per-workspace scheduling fields and rate-limit safety.
18. Build the ad-library API router (`backend/app/api/v1/ad_library.py`,
    registered in `backend/app/api/v1/router.py` under
    `/workspaces/{workspace_id}/ad-library`): `POST /search` (creates a
    `LeadDiscoveryJob` + returns it), `GET /jobs/{id}` status, and request
    validation via `ServiceErrorRoute`; verify with `.ezcoder/eyes/http.sh`.
19. Add advertiser endpoints to the router: `GET /advertisers` (filter + sort by
    `opportunity_score`, ICP filters, pagination), `GET /advertisers/{id}`
    (with creatives + signal breakdown + traced contact), and a service method
    layer (`AdLibraryService`) that enforces workspace scoping; verify responses
    + no cross-tenant leakage with `.ezcoder/eyes/http.sh`.
20. Add saved-monitor CRUD + promotion endpoints: `GET/POST/PATCH/DELETE
    /monitors` (persist saved searches/ICP thresholds + schedule),
    `POST /advertisers/{id}/promote` (advertiser→prospect→contact + optional
    mission enrollment), and `POST /advertisers/bulk-promote`; back them with
    the promotion service from step 16.
21. Regenerate typed API contracts: run `make ci.codegen`, commit
    `backend/openapi.json` + `frontend/src/lib/api/_generated.ts`, add
    `adLibrary` query keys to `frontend/src/lib/query-keys.ts`, and create the
    frontend API client `frontend/src/lib/api/ad-library.ts` with query options.
22. Build the Ad Library search UI: route
    `frontend/src/app/find-leads/ad-library/page.tsx` (+ client/loading/error)
    and `frontend/src/components/ad-library/search-form.tsx` — platform, country,
    keyword vs page, date window, and ICP-signal toggles (long-runner, low-
    diversity, no-testing) — that launches a discovery job and shows job status.
23. Build the ranked advertiser results table
    (`frontend/src/components/ad-library/advertiser-table.tsx`): columns for
    opportunity score, longest-running days, distinct creatives, refresh rate,
    continuity, contact-found state; sortable/filterable; uses
    `page-state.tsx` for loading/empty/error.
24. Build the advertiser detail drawer
    (`frontend/src/components/ad-library/advertiser-detail.tsx`): ad gallery
    (snapshot links/media when available), signal breakdown with the
    human-readable `reasons[]`, delivery timeline, and traced contact info with
    provenance/evidence.
25. Build CRM ingestion + monitors UI: "Add to CRM / Start outreach" actions
    (single + bulk promote, optional mission selection) and a monitors
    management view (`frontend/src/components/ad-library/monitors.tsx`) to
    create/run/schedule saved ICP searches, with toasts + query invalidation.
26. Add cross-cutting safety: a shared provider rate-limiter + cost meter and
    response caching/idempotency for ad-library provider calls
    (`backend/app/services/ad_intelligence/rate_limit.py` reusing
    `app/services/rate_limiting`), so re-scans and multi-replica deploys never
    exceed the Meta 200/hr tier; surface usage in logs.
27. Add compliance + privacy handling: ToS/robots gating for any scrape path, a
    feature-flag wall around raw scraping vs official/licensed APIs, PII
    encryption parity for traced emails/phones, suppression/opt-out checks
    before promotion/outreach, and credential masking in API responses;
    document the policy in `backend/docs/`.
28. Write the test suite: backend pytest for each provider (mock Graph API +
    fixtures), signal math, upsert/dedupe, prospect generation, enrichment,
    promotion, and ad-library API (workspace scoping); a Playwright e2e for the
    ad-library search→results→promote flow; run `make ci.all`.
29. Ship ops + docs: env vars + worker enable settings documented, a runbook in
    `backend/docs/ad-library.md` (API limits, third-party fallback setup,
    rate-limit tuning, EU vs US coverage caveats), `.env.example` updates, and a
    final end-to-end verification pass using the `.ezcoder/eyes` probes.
```
