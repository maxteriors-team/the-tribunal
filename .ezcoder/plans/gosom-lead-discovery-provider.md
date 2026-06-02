# Gosom Google Maps Lead-Discovery Provider

## Goal

Add a second, free-ish, high-volume Google Maps source for the Outbound
Mission / Lead Miner without touching the existing Google Places code paths.
The new provider wraps a self-hosted [gosom/google-maps-scraper] REST API
(running locally or on a sidecar) and presents itself behind the existing
`LeadDiscoveryProvider` protocol so the lead miner can pick between Google
Places and gosom by `source_type`.

[gosom/google-maps-scraper]: https://github.com/gosom/google-maps-scraper

## What the gosom REST API actually looks like

Verified directly against `gosom/google-maps-scraper@main`:

* `web/web.go` registers three endpoints:
  * `POST /api/v1/jobs` → create scrape job. Body is JSON
    (`{"Name": "...", "keywords": [...], "lang": "en", "zoom": 15, "lat": "0",
    "lon": "0", "fast_mode": false, "radius": 10000, "depth": 1,
    "email": false, "extra_reviews": false, "max_time": 600, "proxies": []}`).
    Response: `201 Created` with `{"id": "<uuid>"}`. On bad body: `422`.
* `GET /api/v1/jobs/{id}` → returns the `Job` object (`{"ID": "...",
  "Name": "...", "Date": "...", "Status": "pending|working|ok|failed",
  "Data": {...}}`). `404` if missing.
* `GET /api/v1/jobs/{id}/download` → streams the result CSV (`Content-Type:
  text/csv`). Only available when status is `ok`.
* `web/job.go` defines `JobData` and the four status constants
  (`pending`/`working`/`ok`/`failed`). Server multiplies `max_time` by
  `time.Second` after JSON decode, so we send an int (seconds).
* `gmaps/entry.go` defines the CSV column order: `input_id, link, title,
  category, address, open_hours, popular_times, website, phone, plus_code,
  review_count, review_rating, reviews_per_rating, latitude, longitude, cid,
  status, descriptions, reviews_link, thumbnail, timezone, price_range,
  data_id, place_id, images, reservations, order_online, menu, owner,
  complete_address, about, user_reviews, user_reviews_extended, emails`.
  `emails` is `", "`-joined. `phone`/`website`/`review_rating`/`review_count`
  are plain strings/numbers; everything else complex is `stringify`'d JSON.

Validation on the server side (`web/job.go::JobData.Validate`): non-empty
`keywords`, `lang` must be exactly 2 chars, `depth > 0`, `max_time > 0`,
and if `fast_mode` then `lat` and `lon` must be non-empty.

## Files added

| Path | Purpose |
|---|---|
| `backend/app/services/lead_discovery/gosom_provider.py` | New `GosomMapsLeadProvider` implementing `BaseLeadDiscoveryProvider`. |
| `backend/tests/services/lead_discovery/test_gosom_provider.py` | Mocked HTTP test suite (no live gosom service). |

## Files edited

| Path | Why |
|---|---|
| `backend/app/core/config.py` | New `gosom_*` settings (base URL, timeout, polling, defaults, disabled fallback). |
| `backend/.env.example` | Document the new env vars. |
| `backend/app/services/lead_discovery/__init__.py` | Re-export `GosomMapsLeadProvider` for the lead miner factory. |
| `backend/app/services/lead_discovery/providers/__init__.py` | Re-export from `providers` for symmetry with `GooglePlacesLeadProvider`. |

> Note: the provider module lives directly under `lead_discovery/` (not
> `providers/`) per the explicit task instruction. To keep package-level
> exports symmetric we also surface it from `providers/__init__.py` via a
> re-import.

## New config in `backend/app/core/config.py`

Add after the existing `# Google Places API` block, near line 81:

```python
# gosom/google-maps-scraper — optional self-hosted Google Maps scraper.
# Leave gosom_base_url empty to disable the provider (fallback off);
# the lead miner then falls back to its other configured sources.
gosom_base_url: str = ""
gosom_request_timeout_seconds: float = 30.0
gosom_poll_interval_seconds: float = 5.0
gosom_poll_max_wait_seconds: float = 900.0
gosom_default_depth: int = 1
gosom_default_concurrency: int = 4  # Reserved (not transmitted over REST).
gosom_default_email_extraction: bool = True
gosom_default_extra_reviews: bool = False
gosom_default_lang: str = "en"
gosom_default_max_time_seconds: int = 600
```

`gosom_default_concurrency` is documented as "reserved" because the REST
JobData body has no concurrency field (the CLI `-c` flag isn't surfaced via
HTTP). Keeping the setting future-proofs us against a gosom REST change and
also lets ops dashboards record the intended concurrency for audit.

Mirror these in `backend/.env.example`:

```env
# gosom/google-maps-scraper (optional). Leave GOSOM_BASE_URL empty to disable.
GOSOM_BASE_URL=
GOSOM_REQUEST_TIMEOUT_SECONDS=30
GOSOM_POLL_INTERVAL_SECONDS=5
GOSOM_POLL_MAX_WAIT_SECONDS=900
GOSOM_DEFAULT_DEPTH=1
GOSOM_DEFAULT_CONCURRENCY=4
GOSOM_DEFAULT_EMAIL_EXTRACTION=true
GOSOM_DEFAULT_EXTRA_REVIEWS=false
GOSOM_DEFAULT_LANG=en
GOSOM_DEFAULT_MAX_TIME_SECONDS=600
```

## New module: `app/services/lead_discovery/gosom_provider.py`

Shape (Python 3.12, ruff/pyright strict-compatible):

```python
SOURCE_TYPE = "gosom_google_maps"

class GosomServiceDisabledError(LeadDiscoveryProviderError):
    """Raised when the gosom base URL is not configured."""

class GosomJobFailedError(LeadDiscoveryProviderError):
    """Raised when the gosom job reaches the ``failed`` status."""

class GosomMapsLeadProvider(BaseLeadDiscoveryProvider):
    source_type: ClassVar[str] = SOURCE_TYPE

    def __init__(
        self,
        *,
        base_url: str | None = None,
        request_timeout_seconds: float | None = None,
        poll_interval_seconds: float | None = None,
        poll_max_wait_seconds: float | None = None,
        default_depth: int | None = None,
        default_concurrency: int | None = None,
        default_email_extraction: bool | None = None,
        default_extra_reviews: bool | None = None,
        default_lang: str | None = None,
        default_max_time_seconds: int | None = None,
        client: httpx.AsyncClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None: ...

    async def search(self, request: LeadDiscoveryRequest) -> ProviderResult: ...
    async def close(self) -> None: ...
```

Behavior:

1. `search()` short-circuits with a `DiscoveryWarning("empty_query", ...)`
   when `request.query` is empty/whitespace — same contract as
   `GooglePlacesLeadProvider`.
2. If `base_url` is empty, raises `GosomServiceDisabledError`
   immediately so the lead miner can surface a clean "provider disabled"
   reason. (Subclass of `LeadDiscoveryProviderError`.)
3. POSTs `{Name, JobData}` to `{base_url}/api/v1/jobs`. `JobData` is built
   from request + defaults: keywords are `[request.query]`, single-keyword
   per job to keep the row mapping deterministic. `extra_reviews=False`,
   `email`, `depth`, `lang`, `max_time` (seconds, int) from defaults
   unless overridden in `request.params` (provider-specific extras:
   `params={"depth": 2, "email": False, "extra_reviews": True,
   "lang": "de", "max_time": 1200, "lat": "...", "lon": "...",
   "fast_mode": True, "radius": 5000, "zoom": 15, "proxies": [...]}`).
4. Reads `{"id": "..."}` from `201`. On non-2xx maps:
   * `401`/`403` → `LeadDiscoveryAuthError`
   * `429` → `LeadDiscoveryRateLimitError` (honors `Retry-After` for the
     internal retry loop)
   * `422` → `LeadDiscoveryProviderError` with the server's `message`
   * `5xx` → retried with exponential backoff (3 attempts max, capped by
     `gosom_request_timeout_seconds`); final failure → `LeadDiscoveryProviderError`
   * `httpx.TimeoutException` / `httpx.NetworkError` → retried up to 3
     times → `LeadDiscoveryProviderError`
5. Polls `GET /api/v1/jobs/{id}` every `poll_interval_seconds`, capped at
   `poll_max_wait_seconds`. Status mapping: `ok` → break and download;
   `failed` → raise `GosomJobFailedError`; `pending`/`working` → sleep
   and retry; unexpected status → `DiscoveryWarning("unknown_job_status",
   ...)`, treat as still working.
6. On `ok` downloads `GET /api/v1/jobs/{id}/download` (text/csv). Streams
   the body with `client.stream()` is overkill — the entire CSV fits in
   memory for typical jobs; uses `client.get()` and decodes
   `response.content.decode("utf-8", errors="replace")`. Parses with
   `csv.DictReader(io.StringIO(text))`.
7. CSV→`RawLead` mapping (per row):
   * `name` ← `title`
   * `source_external_id` ← `place_id` (fallback `cid`, `data_id`)
   * `phone_number` ← `phone`
   * `website` ← `website`
   * `website_host` ← `extract_host(website)`
   * `email` ← first entry of `emails.split(", ")` (None when blank);
     when more than one, the rest go into `source_metadata["emails_extra"]`
   * `address` ← `address`
   * `rating` ← `float(review_rating)` if non-empty
   * `review_count` ← `int(review_count)` if non-empty, else 0
   * `types` ← `tuple(filter(None, category.split("|")))` (single entry
     per the gosom schema, but stays robust if upstream changes)
   * `country_code`/`region`/`city`/`location_label` ← propagated from
     `request` (we don't try to re-parse `complete_address`)
   * `source_metadata` keeps `link`, `latitude`, `longitude`,
     `plus_code`, `cid`, `place_id`, `data_id`, `status`,
     `emails_extra`, `source_query`, `job_id`, raw `review_count` /
     `review_rating` strings for forensic use
   * Rows missing both `title` and `place_id` are skipped with a
     `DiscoveryWarning("blank_row", ...)`.
8. Runs `dedupe_raw_leads()` and returns `ProviderResult`. `max_results`
   from request truncates after dedupe to honor the soft cap.
9. `close()` aclose's the owned httpx client; injected clients/transports
   are left alone.

### HTTP / retry plumbing

The provider builds a single `httpx.AsyncClient` lazily (mirrors
`GooglePlacesService.get_client`). When `transport` is passed it's used
verbatim (this is the test seam — `httpx.MockTransport`). When a `client`
is passed, the provider trusts it and doesn't close it on shutdown.

Retry loop: hand-written for parity with `GooglePlacesService` (3
attempts, backoff starting at 1s capped at 30s, immediate `await sleep(0)`
in tests via the injected `sleep` callable so no real time elapses).

The `clock` + `sleep` injections let tests advance "time" deterministically
for the poll loop and the timeout cap without monkey-patching globals.

## New tests: `tests/services/lead_discovery/test_gosom_provider.py`

Async test module (pytest's `asyncio_mode = "auto"` covers the
decorators). Uses `httpx.MockTransport` so no real network calls happen.

Tests:

1. **`TestProtocolCompliance.test_implements_protocol`** — `isinstance`
   against `LeadDiscoveryProvider`; `source_type == "gosom_google_maps"`.
2. **`TestDisabledFallback.test_blank_base_url_raises`** — empty
   `gosom_base_url` triggers `GosomServiceDisabledError` (sub-class of
   `LeadDiscoveryProviderError`). Test that this raises *without* doing
   any HTTP — pass a `MockTransport` that asserts no calls.
3. **`TestEmptyQuery.test_blank_query_returns_warning`** — empty query
   short-circuits with `DiscoveryWarning("empty_query")` and never
   touches the mock transport.
4. **`TestHappyPath.test_full_flow_create_poll_download`** — three-stage
   mock transport: `POST /api/v1/jobs` → `201 {"id": "j1"}`; first two
   `GET /api/v1/jobs/j1` → `{"Status": "working"}`; third →
   `{"Status": "ok"}`; `GET /api/v1/jobs/j1/download` → returns a CSV
   payload with two rows. Asserts ordered `RawLead` fields including
   email split, rating coercion, host extraction, metadata propagation,
   `source_metadata["emails_extra"]` for the second email.
5. **`TestHappyPath.test_request_body_carries_defaults_and_overrides`** —
   captures `httpx.Request` for the create call, asserts JSON body has
   `keywords=[query]`, `depth`, `email`, `lang`, `max_time` from
   provider defaults; verifies `request.params` overrides (e.g.
   `depth=3`, `email=False`, `lat`/`lon`, `fast_mode`).
6. **`TestErrorMapping.test_401_returns_auth_error`** — POST returns
   `401`, mapped to `LeadDiscoveryAuthError`.
7. **`TestErrorMapping.test_403_returns_auth_error`** — same for `403`.
8. **`TestErrorMapping.test_429_returns_rate_limit_error`** — POST
   returns `429` with `Retry-After: 0`; final raise is
   `LeadDiscoveryRateLimitError` after retries.
9. **`TestErrorMapping.test_422_returns_provider_error`** — POST
   returns `422` with `{"code": 422, "message": "missing depth"}` —
   `LeadDiscoveryProviderError` carrying the message; no auth/ratelimit
   subclass.
10. **`TestErrorMapping.test_5xx_retried_then_provider_error`** — POST
    returns `503` three times; provider raises
    `LeadDiscoveryProviderError`. Asserts the retry counter (3 calls)
    via the captured request log.
11. **`TestErrorMapping.test_job_status_failed_raises`** — create
    succeeds, poll returns `{"Status": "failed", "Error": "blocked"}`;
    `GosomJobFailedError` raised.
12. **`TestErrorMapping.test_poll_timeout_raises`** — every poll returns
    `working`; with `poll_max_wait_seconds=0.05` and a fake clock the
    provider raises `LeadDiscoveryProviderError` referencing "timed out".
13. **`TestParsing.test_blank_row_skipped_with_warning`** — CSV has one
    valid row and one row with empty `title` and empty `place_id`;
    `result.warnings` contains `DiscoveryWarning("blank_row")`; lead
    count == 1.
14. **`TestParsing.test_missing_optional_columns_become_none`** —
    `phone`, `website`, `emails`, `review_rating`, `review_count`
    blank; lead fields become `None`/`0`.
15. **`TestParsing.test_dedupe_within_batch`** — two rows with same
    phone; `result.duplicate_count == 1`, `result.lead_count == 1`.
16. **`TestLifecycle.test_close_closes_owned_client`** — provider built
    with `transport=...` (so it owns the client) → `close()` aclose's
    it; subsequent `search()` rebuilds.
17. **`TestLifecycle.test_close_skips_injected_client`** — passing
    `client=httpx.AsyncClient(...)` skips closing on `close()`.

All tests use an in-memory `httpx.MockTransport`. Tests inject
`sleep=AsyncMock()` and a deterministic `clock=lambda: time_counter[0]`
so polling tests are instant.

## Verification

After implementation, from `backend/`:

```bash
uv run ruff check app tests
uv run mypy app
uv run pytest tests/services/lead_discovery
```

All three must pass clean before commit. Final commit via the
`commit-work` skill.

## Risks / non-goals

* **Concurrency setting is not transmitted.** The gosom REST `JobData`
  has no concurrency field. The setting is preserved for parity with the
  CLI flag and forward compatibility; document this in the provider
  docstring so future readers don't expect it to wire through.
* **CSV-only download.** The REST endpoint only serves CSV. JSON output
  exists in the CLI but not the API. We parse CSV with `csv.DictReader`
  and tolerate empty cells.
* **Single keyword per job.** The gosom REST accepts multiple keywords
  in one job, but the lead-miner protocol gives us one query per call.
  Multi-keyword fan-out is the orchestrator's job, not the provider's.
* **No persistent job tracking.** The provider deletes nothing — gosom
  retains jobs locally. Cleanup is the operator's responsibility.
* **No external service in tests.** `httpx.MockTransport` covers create,
  poll, and download. Real gosom is not exercised here.

## Steps

1. Add new `gosom_*` settings to `backend/app/core/config.py` and document them in `backend/.env.example`.
2. Implement `backend/app/services/lead_discovery/gosom_provider.py` with `GosomMapsLeadProvider`, error subclasses, and the create→poll→download flow.
3. Re-export `GosomMapsLeadProvider`, `GosomServiceDisabledError`, and `GosomJobFailedError` from `backend/app/services/lead_discovery/__init__.py` and `backend/app/services/lead_discovery/providers/__init__.py`.
4. Add `backend/tests/services/lead_discovery/test_gosom_provider.py` covering protocol compliance, disabled fallback, empty query, happy path with CSV parsing, request-body assertion, every error-mapping branch, polling timeout, blank-row warning, within-batch dedupe, and lifecycle ownership.
5. Run `uv run ruff check app tests`, `uv run mypy app`, and `uv run pytest tests/services/lead_discovery` from `backend/`; fix any findings until clean.
6. Use the `/commit` (`commit-work`) skill to craft the final commit message.
