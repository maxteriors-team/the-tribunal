# Ad Library — In-House Self-Scrape (own the data source)

This is the **operator note** for the in-house Meta Ad Library scraper. It lets
the discover → rank → promote → CRM → call pipeline run on live **US commercial**
advertisers pulled from Meta's *public* Ad Library, instead of depending on a
paid third-party ad API.

> **Read the risk posture first. This ships OFF by default and is a conscious,
> auditable operator opt-in — not a default capability.** Not legal advice.

## Why this exists

The official Graph `/ads_archive` API only returns **political/issue** ads for
non-EU commercial searches (a commercial roofing search returns Graph error code
10). The public Ad Library **website**, however, renders commercial ads with no
login. It is powered by an internal endpoint:

```
POST https://www.facebook.com/ads/library/async/search_ads/
```

which returns `for (;;);`-prefixed JSON with ads under `payload.results` — the
**same internal ad shape** our licensed third-party provider already normalizes
(`snapshot.body.text`, `snapshot.cards[]`, `is_active`, `start_date`/`end_date`
epochs, `publisher_platform`). Page-name → numeric page id resolves via the
sibling `async/search_typeahead/` endpoint.

The self-scrape provider calls those endpoints itself and feeds the raw ad dicts
into the **same** normalizer + persistence + signal + promotion rails — nothing
downstream changes.

## How it's gated

Two switches must **both** be on (defence in depth):

| Setting | Default | Meaning |
|---|---|---|
| `AD_LIBRARY_ALLOW_RAW_SCRAPE` | `false` | Master wall around *any* raw scraping (cf. *Meta v. Bright Data* + Meta ToS). |
| `META_SELF_SCRAPE_ENABLED` | `false` | Opt into the in-house scraper specifically. |

With both on, the provider factory prefers `MetaScraperProvider` for the `meta`
platform. The official Graph API token path stays configured as an **automatic
fallback**, so a scrape break degrades instead of hard-failing. The provider
also calls `compliance.ensure_self_scrape_allowed()` on every search, which
raises a mappable 503 unless the master wall is open — so flipping
`META_SELF_SCRAPE_ENABLED` alone does nothing.

## Fetch strategies

| `META_SCRAPE_STRATEGY` | Dependency | Trade-off |
|---|---|---|
| `token_http` (default) | none (httpx) | Loads the Ad Library page, regexes the **LSD CSRF token** + cookies, caches them in Redis (`META_SCRAPE_SESSION_TTL_SECONDS`), POSTs the async endpoints, re-bootstraps once on 401/403. Cheapest; most brittle to markup/WAF churn. |
| `headless` | Playwright Chromium (optional, lazily imported) | A real browser produces valid tokens + a browser-grade TLS fingerprint, then issues the async POSTs through the browser context. Survives token/markup churn; needs `pip`/`uv` Playwright + `npx playwright install chromium`. |

If `headless` is selected without Playwright installed, the provider raises a
clear, actionable error (it never crashes with a bare `ImportError`).

## ⚠️ Production (Railway) will likely be blocked without a proxy

Meta serves **403 / login-redirect / challenge** pages to **datacenter IPs**.
Our backend runs on **Railway, a datacenter IP**, so the scraper will very
likely be blocked there **without a residential/ISP proxy**:

```
META_SCRAPE_PROXY_URL=http://user:pass@residential-proxy.example:port
```

Honest caveat: a residential proxy is itself an external dependency you may end
up paying for. The "no third party" goal is fully achievable for the
**parsing/pipeline**; the **network egress** may still need a paid proxy to be
reliable at scale on Railway. **Local/dev from a residential IP works without a
proxy.**

## Rate limiting (be gentle — this is not a firehose)

Scraping must be far gentler than the ~200/hr official tier to avoid WAF bans:

| Setting | Default | Purpose |
|---|---|---|
| `META_SCRAPE_RATE_LIMIT_PER_HOUR` | `40` | Distinct, low hourly cap for the scrape path (own Redis bucket, separate from the official tier). |
| `META_SCRAPE_MIN_DELAY_SECONDS` / `META_SCRAPE_MAX_DELAY_SECONDS` | `2.0` / `5.0` | Jittered delay between paginated pages. |
| `META_SCRAPE_SESSION_TTL_SECONDS` | `1800` | How long a harvested LSD token + cookies are reused (shared across replicas via Redis). |

Expect **tens-to-low-hundreds of advertisers per run** — plenty for daily sales
prospecting, not a bulk crawler.

## How to enable (local/dev, residential IP)

```bash
# backend/.env
AD_LIBRARY_ALLOW_RAW_SCRAPE=true
META_SELF_SCRAPE_ENABLED=true
META_SCRAPE_STRATEGY=token_http
# META_SCRAPE_PROXY_URL=   # leave blank on a residential IP; required on Railway
```

Then run a normal Ad Library search (e.g. `roofing`) through the existing
`/api/v1/.../ad-library/search` endpoint or a saved monitor. The discovery
worker produces real `AdAdvertiser` rows; promoting one creates a CRM `Contact`
exactly as with the official provider.

## Honest caveats

1. **Terms of Service.** Programmatic scraping of `facebook.com/ads/library` is
   against Meta's ToS regardless of the data being "public". Owning the code
   does not remove the ToS question — enabling it is accepting that risk
   consciously. Not legal advice.
2. **Brittleness.** Token names, the `search_ads` param set, and the response
   shape change without notice. Mitigations: the `headless` strategy, the
   recorded-fixture tests (`test_meta_scraper_provider.py`) that catch shape
   drift fast, and the official API as an automatic fallback.
3. **Phone-number gate still applies.** Even with live advertisers, promotion
   still requires a scrapeable phone (existing `promotion.py` behavior). This
   provider fixes *supply of advertisers*, not the separate phone-coverage gap.
4. **Do not smoke-test against prod/Railway** — document/provision the proxy
   first.
