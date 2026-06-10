# Ad Library Prospecting — Runbook

This feature finds advertisers who **already spend on ads but run the same
creatives for months** (consistent, long-running, low creative-iteration), traces
their contact info, and ingests qualified advertisers into the CRM as prospects
→ contacts → outreach. It plugs into the existing outbound-mission rails.

See also: [ad-library-compliance.md](./ad-library-compliance.md) for the
ToS/PII/credential policy.

## Architecture (one pass)

```
Ad library (Meta / Google)
        │  providers (official API default; third-party + SerpApi config-gated)
        ▼
[AdAdvertiser + AdCreative]  ← idempotent upsert (ad_store), tracked over time
        │  signal engine (signals.py): longest-run, distinct creatives,
        │  refresh rate, continuity → opportunity_score + reasons + example ad
        ▼  ICP filter (icp.py): floors + exclude prolific testers
[LeadProspect]  → prospect_enrichment_worker (contact tracing + website intel)
        ▼
[Contact] (+ optional Opportunity)  ← prospect_promotion_worker / API promote
        │  carries the specific ad to reference into business_intel
        ▼
[OutboundMission sequence]  (existing outreach)
```

Workers (all in-process, poll-based, `skip_locked`):

| Worker | Does | Enable flag |
|---|---|---|
| `ad_library_discovery_worker` | Runs pending ad-library jobs → advertisers + signals | `AD_LIBRARY_DISCOVERY_WORKER_ENABLED` |
| `prospect_enrichment_worker` | Enriches `LeadProspect` (trace + website + email finder) | `PROSPECT_ENRICHMENT_WORKER_ENABLED` |
| `prospect_promotion_worker` | Promotes enriched prospects → contacts | `PROSPECT_PROMOTION_WORKER_ENABLED` |
| `ad_monitor_worker` | Re-schedules saved monitors (re-scan over time) | `AD_MONITOR_WORKER_ENABLED` |

## Setup

1. **Meta token (default path).** Create a Meta developer app, generate a user
   access token with `ads_read`, and either:
   - set it per-workspace via a `meta_ad_library` integration
     (`POST /api/v1/workspaces/{id}/integrations` with
     `{"integration_type":"meta_ad_library","credentials":{"access_token":"…"}}`),
     **preferred**; or
   - set `META_AD_LIBRARY_ACCESS_TOKEN` for single-tenant/dev.
   Bump `META_AD_LIBRARY_API_VERSION` ~annually (v17 and earlier error).

2. **Third-party fallback (optional, fuller US commercial coverage).** Set
   `META_THIRDPARTY_ENABLED=true`, `META_THIRDPARTY_PROVIDER`
   (`apify|scrapecreators|serpapi`), `META_THIRDPARTY_API_KEY`,
   `META_THIRDPARTY_BASE_URL`. Requests opt in per-search via
   `use_thirdparty_fallback`.

3. **Google Ads Transparency (optional).** No official API; set
   `GOOGLE_ADS_TRANSPARENCY_ENABLED=true` + `SERPAPI_API_KEY` (or a per-workspace
   `google_ads_transparency` integration).

4. **Email finder (optional).** `EMAIL_FINDER_PROVIDER=hunter|apollo` +
   `EMAIL_FINDER_API_KEY` to backfill emails when public tracing fails.

## API

Base: `/api/v1/workspaces/{workspace_id}/ad-library`

| Method | Path | Purpose |
|---|---|---|
| POST | `/search` | Launch a search → returns a `LeadDiscoveryJob` (202). |
| GET | `/jobs/{id}` | Job status. |
| GET | `/advertisers` | Ranked advertisers (`?only_qualified=true` applies ICP). |
| GET | `/advertisers/{id}` | Detail: creatives, signal breakdown, traced contact. |
| POST | `/advertisers/{id}/promote` | Advertiser → prospect → contact. |
| POST | `/advertisers/bulk-promote` | Bulk promote. |
| GET/POST | `/monitors` | List / create saved monitors. |
| PATCH/DELETE | `/monitors/{id}` | Update / delete a monitor. |

## ICP tuning

Defaults select "consistent but not testing" and **exclude prolific testers**
(the 20–100 UGC-variation crowd). Per-search or per-monitor overrides via
`icp_thresholds`:

| Threshold | Default | Direction |
|---|---|---|
| `min_continuity_score` | 0.5 | floor — must spend consistently |
| `min_longest_running_days` | 60 | floor — has a stale long-runner |
| `min_active_ads` | 1 | floor — currently live |
| `min_opportunity_score` | 50 | floor — overall fit |
| `max_distinct_creatives` | 8 | **ceiling — exclude testers** |
| `max_active_creatives` | 12 | **ceiling — exclude testers** |
| `max_creative_refresh_rate` | 4.0 | **ceiling — exclude testers** |

## Rate limits & coverage caveats

- Meta default tier ≈ **200 calls/hour/app**. We cap globally at
  `META_AD_LIBRARY_RATE_LIMIT_PER_HOUR` (180) in Redis so re-scans + multiple
  replicas share one budget. 429/`Retry-After`/`X-App-Usage` are handled; a
  rate-limited job stays `pending` and retries next cycle.
- **EU/UK commercial** coverage on the official API is strong (post-DSA);
  **US/non-EU commercial** returns can be incomplete vs the web UI — that's why
  the third-party provider exists.
- Spend/impressions are **political-only** and not needed: the signal is
  computed purely from delivery dates + creative metadata.

## Operating / debugging

- Worker logs: `.ezcoder/eyes/logs.sh --service backend --grep "ad_library_discovery_worker|ad_monitor_worker|prospect_enrichment_worker|prospect_promotion_worker"`.
- Trigger a search and watch a job:
  `POST /ad-library/search` then poll `GET /ad-library/jobs/{id}`.
- Usage meter: `ad_library:rate:*` / `ad_library:cost:*` Redis keys (per hour).
- To pause the pipeline without a deploy, set the relevant `*_WORKER_ENABLED`
  flag to `false`.
