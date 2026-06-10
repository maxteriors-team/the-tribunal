# Ad Library Prospecting — Compliance & Privacy Policy

This feature pulls advertisers from **public** ad libraries (Meta Ad Library,
Google Ads Transparency Center), scores them for the "consistent but not
testing" ICP, traces public contact info, and ingests qualified advertisers
into the CRM as prospects → contacts → outreach.

## Data sources & legal posture

| Source | Access | Notes |
|---|---|---|
| Meta Ad Library | Official Graph API (`/ads_archive`) | Default. Public data; requires a Meta developer-app token with `ads_read`. No spend/impressions for commercial ads — we don't need them. |
| Meta (fuller US coverage) | Licensed third-party API (Apify / ScrapeCreators / SerpApi) | **Config-gated, off by default.** Used only when a key is configured. |
| Google Ads Transparency | SerpApi adapter | **Feature-flagged, off by default.** No official API exists. |
| Raw scraping | — | **Hard-disabled.** Behind `ad_library_allow_raw_scrape`; no crawler ships. |

We prefer the official API and licensed third-party APIs over raw scraping.
Meta's ToS restricts scraping (cf. *Meta v. Bright Data*), so any raw-scrape
path is walled behind `ad_library_allow_raw_scrape` and ships disabled. The
Google provider's raw fallback is a documented no-op stub — it returns an empty
result with a warning rather than performing an unsanctioned crawl.

## Snapshot / creative media

The Meta `ad_snapshot_url` is the only path to rendered creative media and it
**embeds the access token**. We:

- never log the snapshot URL (tokens are stripped via
  `compliance.redact_snapshot_url`);
- strip token-bearing fields from any persisted `raw_payload`;
- gate optional headless rendering behind
  `ad_library_snapshot_rendering_enabled` (off by default) to avoid a heavy
  browser dependency and stay off a scraping path.

The signal engine and outreach need only metadata
(`ad_delivery_start_time`/`stop_time`, creative bodies/links), so media
rendering is never required.

## PII handling

- Traced **emails/phones** are PII. They are written only to the encrypted
  `LeadProspect` / `Contact` columns (Fernet at rest) with BLAKE2b lookup
  hashes — never to the plaintext `ad_advertisers` row.
- API responses **mask** integration credentials
  (`integrations/credentials.mask_credentials`) and the advertiser detail's
  `traced_contact` surfaces only booleans (`has_email`, `has_phone`), not raw
  values.
- Promotion runs through the existing **global opt-out / suppression** check
  before any contact is created; opted-out phones flip the prospect to
  `suppressed` and are never promoted.

## Rate limiting & cost

- A global hourly cap (`meta_ad_library_rate_limit_per_hour`, default 180,
  under Meta's ~200/hr tier) is enforced in Redis so re-scans + multiple
  replicas share one budget.
- A per-platform/hour cost meter is recorded for ops visibility.
- Identical searches within a short window reuse a cached result.
- Upstream 429 / `Retry-After` / `X-App-Usage` are handled and surfaced; the
  rate gate fails *open* so a Redis outage never wedges discovery.

## Configuration summary

| Setting | Default | Purpose |
|---|---|---|
| `ad_library_enabled` | `true` | Master switch for the feature. |
| `meta_ad_library_access_token` | `""` | Global fallback Meta token (per-workspace `WorkspaceIntegration` preferred). |
| `meta_ad_library_rate_limit_per_hour` | `180` | Global hourly provider-call cap. |
| `meta_thirdparty_enabled` / `meta_thirdparty_api_key` | `false` / `""` | Config-gated third-party Meta fallback. |
| `google_ads_transparency_enabled` / `serpapi_api_key` | `false` / `""` | Google Ads Transparency via SerpApi. |
| `ad_library_allow_raw_scrape` | `false` | Hard wall around raw scraping. |
| `ad_library_snapshot_rendering_enabled` | `false` | Opt-in headless creative rendering. |
| `email_finder_provider` / `email_finder_api_key` | `""` | Optional Hunter/Apollo email finder. |
