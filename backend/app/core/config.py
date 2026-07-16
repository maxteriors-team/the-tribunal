"""Application configuration."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Database
    database_url: str = "postgresql+asyncpg://aicrm:aicrm_dev_password@localhost:5432/aicrm"
    db_pool_size: int = 5
    db_max_overflow: int = 10

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Security
    # SECRET_KEY signs all JWT access/refresh tokens. Required from environment —
    # the app refuses to boot without it. Generate with: `openssl rand -hex 32`.
    secret_key: str = Field(..., min_length=32)
    encryption_key: str = "change-me-in-production"  # Used for Fernet encryption of credentials
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30  # 30 minutes (short-lived)
    refresh_token_expire_days: int = 7  # 7 days (long-lived)
    cookie_secure: bool | None = None  # None = secure unless local development

    # OpenAI
    openai_api_key: str = ""
    openai_oauth_access_token: str = ""
    openai_oauth_refresh_token: str = ""
    openai_oauth_expires_at: int | None = None
    openai_oauth_account_id: str = ""
    openai_oauth_client_id: str = ""
    openai_oauth_redirect_uri: str = ""
    openai_oauth_token_url: str = "https://auth.openai.com/oauth/token"
    openai_oauth_originator: str = ""
    openai_oauth_user_agent: str = ""
    openai_realtime_model: str = "gpt-realtime-2"
    # Image model for the estimator's photorealistic night render (Phase 2).
    openai_estimate_render_model: str = "gpt-image-2"
    openai_realtime_client_secret_ttl_seconds: int = 600
    openai_realtime_idle_timeout_ms: int | None = 6000
    openai_codex_voice_enabled: bool = False
    openai_timeout: int = 60

    # Telnyx
    telnyx_api_key: str = ""
    telnyx_webhook_secret: str = ""
    telnyx_public_key: str = ""
    skip_webhook_verification: bool = False
    # Telnyx Voice
    telnyx_connection_id: str = ""  # Required for outbound calls

    # Text messaging provider selection
    text_message_provider: str = "telnyx"  # telnyx | mac_relay

    # Self-hosted Mac iMessage relay
    mac_relay_base_url: str = ""
    mac_relay_token: str = ""
    mac_relay_webhook_token: str = ""
    mac_relay_backend_webhook_url: str = ""
    mac_relay_default_service: str = "imessage"  # imessage | sms | auto

    # Cal.com
    calcom_api_key: str = ""
    calcom_webhook_secret: str = ""

    # Jobber (field-service sync). The access token is a short-lived OAuth2
    # token; the CLI also accepts it via --token / JOBBER_ACCESS_TOKEN so the
    # value need not be persisted in app config. Pin the GraphQL schema version
    # so a Jobber-side breaking change can't silently alter responses.
    jobber_access_token: str = ""
    jobber_api_version: str = "2023-11-15"

    # ElevenLabs
    elevenlabs_api_key: str = ""

    # xAI (Grok)
    xai_api_key: str = ""

    # Resend
    resend_api_key: str = ""
    resend_from_email: str = "noreply@example.com"
    resend_from_name: str = "Maxteriors"
    resend_webhook_secret: str = ""

    # Expo Push Notifications
    expo_access_token: str = ""

    # Google Places API
    google_places_api_key: str = ""

    # Ad-library intelligence (Meta Ad Library + Google Ads Transparency).
    # Pulls advertisers from public ad libraries to detect long-running, low-
    # iteration advertisers as outbound prospects. The Meta Ad Library is public
    # data; ``meta_ad_library_access_token`` is a Meta developer-app token with
    # ``ads_read`` used as a single-tenant/dev fallback when a workspace has no
    # ``meta_ad_library`` WorkspaceIntegration configured. Never log the token —
    # the snapshot URL embeds it.
    ad_library_enabled: bool = True
    meta_ad_library_access_token: str = ""
    # Bump roughly annually; v17 and earlier already error. See
    # facebook.com/ads/library/api.
    meta_ad_library_api_version: str = "v22.0"
    meta_ad_library_base_url: str = "https://graph.facebook.com"
    # Default tier is ~200 calls/hour/app; keep a safety margin under that so
    # re-scans + multi-replica deploys never trip 429s.
    meta_ad_library_rate_limit_per_hour: int = 180
    meta_ad_library_request_timeout_seconds: float = 30.0
    meta_ad_library_default_country: str = "US"
    # Config-gated third-party fallback provider for fuller US-commercial
    # coverage (Apify / ScrapeCreators / SerpApi). Off unless a key is present.
    meta_thirdparty_enabled: bool = False
    meta_thirdparty_provider: str = ""  # apify | scrapecreators | serpapi
    meta_thirdparty_api_key: str = ""
    meta_thirdparty_base_url: str = ""
    # In-house self-scrape of the public Ad Library website's internal
    # ``async/search_ads/`` endpoint (no paid third party). Master-gated by
    # ``ad_library_allow_raw_scrape`` below — both must be true to activate.
    # ``token_http`` bootstraps an LSD CSRF token + cookies over plain HTTP;
    # ``headless`` drives Playwright Chromium (heavier, survives token churn).
    # A residential/ISP proxy is effectively required from datacenter IPs
    # (Railway) — datacenter egress draws 403/login challenges. Scrape pacing is
    # deliberately gentle (jittered delay + a low hourly cap) to avoid WAF bans.
    meta_self_scrape_enabled: bool = False
    meta_scrape_strategy: str = "token_http"  # token_http | headless
    meta_scrape_proxy_url: str = ""
    meta_scrape_min_delay_seconds: float = 2.0
    meta_scrape_max_delay_seconds: float = 5.0
    meta_scrape_session_ttl_seconds: int = 1800
    meta_scrape_rate_limit_per_hour: int = 40
    # The Ad Library website now talks to ``POST /api/graphql/`` via persisted
    # queries (the old ``async/search_ads/`` form endpoints return 404). These
    # are Relay ``doc_id`` values captured from live browser traffic on
    # 2026-06-12 (AdLibrarySearchPaginationQuery / the typeahead query); Meta
    # rotates them periodically, so they are overridable without a code change.
    # The ``headless`` strategy is required to clear the initial JS challenge.
    meta_scrape_search_doc_id: str = "24922295957467452"
    meta_scrape_typeahead_doc_id: str = "9755915494515334"
    # Google Ads Transparency Center has no official API; the SerpApi adapter is
    # the lowest-risk path. Fully behind a flag and off by default.
    google_ads_transparency_enabled: bool = False
    serpapi_api_key: str = ""
    serpapi_base_url: str = "https://serpapi.com"
    # Hard wall around raw scraping of ad libraries (Meta ToS restricts it).
    # Must be explicitly enabled; official + licensed APIs are always preferred.
    ad_library_allow_raw_scrape: bool = False
    # Optional headless snapshot rendering of creative media (Phase 2, heavy dep).
    ad_library_snapshot_rendering_enabled: bool = False
    # Worker enable flags + poll cadence for the ad-library pipeline.
    ad_library_discovery_worker_enabled: bool = True
    ad_library_discovery_poll_interval: int = 15
    ad_monitor_worker_enabled: bool = True
    ad_monitor_poll_interval: int = 300
    prospect_enrichment_worker_enabled: bool = True
    prospect_enrichment_poll_interval: int = 30
    prospect_promotion_worker_enabled: bool = True
    prospect_promotion_poll_interval: int = 30
    # Recurring-job materializer: how often (seconds) to generate due jobs from
    # active recurring templates. Hourly is plenty — generation runs days ahead.
    recurring_job_poll_interval: int = 3600
    # Optional config-gated email-finder for prospect enrichment.
    email_finder_provider: str = ""  # hunter | apollo
    email_finder_api_key: str = ""

    # --- People discovery + buying signals (Apollo-parity) ---
    # Web people-extraction discovery worker + crawl caps.
    web_people_discovery_worker_enabled: bool = True
    web_people_discovery_poll_interval: int = 20
    # Max first-party pages crawled per company domain during people extraction.
    web_people_max_pages_per_domain: int = 8
    # Max people emitted per company domain in one discovery run.
    web_people_max_people_per_domain: int = 50
    # Email reveal: pattern inference is always on; verification is opt-in.
    # MX lookup runs when verification is enabled; SMTP/provider probing only
    # when explicitly turned on (slow + can get egress IPs blocked).
    email_verification_enabled: bool = False
    email_verification_smtp_enabled: bool = False
    email_verification_smtp_timeout_seconds: float = 8.0
    email_verification_smtp_from: str = "verify@example.com"
    # Phone reveal: scrape the prospect's own website for a published business
    # line. No paid provider, no name-based inference (impossible for phones).
    phone_reveal_enabled: bool = True
    phone_reveal_max_pages: int = 3
    # Config-gated signal providers — empty key = provider disabled (no data).
    hiring_signal_api_key: str = ""
    funding_signal_api_key: str = ""

    # gosom/google-maps-scraper — optional self-hosted Google Maps scraper.
    # Leave ``gosom_base_url`` empty to disable the provider entirely; the
    # lead miner then falls back to its other configured sources. Point
    # ``gosom_base_url`` at the root of the gosom web server (e.g.
    # ``http://localhost:8080``) — the provider appends ``/api/v1/jobs``
    # internally. ``gosom_default_concurrency`` is reserved: the gosom REST
    # ``JobData`` body has no concurrency field today (the CLI ``-c`` flag
    # isn't surfaced via HTTP), so the provider keeps the setting for future
    # compatibility and for ops dashboards without transmitting it.
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

    # App
    debug: bool = False
    environment: str = "development"
    cors_origins: list[str] = ["http://localhost:3000"]
    api_base_url: str = ""  # Base URL for webhooks (e.g., https://api.example.com)
    frontend_url: str = "http://localhost:3000"  # Frontend URL for links in emails
    public_base_url: str = "http://localhost:8000"  # Public base URL for short link redirects

    @property
    def secure_auth_cookies(self) -> bool:
        """Return whether auth cookies should require HTTPS."""
        if self.cookie_secure is not None:
            return self.cookie_secure
        return self.environment.lower() not in {"development", "local", "test", "testing"}

    # Workers
    # Keep ``True`` for the legacy single-process API+workers topology. Set
    # ``RUN_BACKGROUND_WORKERS=false`` on API-only deployments that should serve
    # HTTP/WebSocket traffic without starting polling loops in-process.
    run_background_workers: bool = True
    campaign_poll_interval: int = 5
    ai_response_delay_ms: int = 2000

    # Enrichment
    enable_ai_enrichment: bool = True  # Toggle AI website summary

    # Revenue / ROI estimation
    # Simple, configurable unit-cost assumptions used by the dashboard ROI
    # ledger to estimate AI spend from message/call volume. These are coarse
    # blended estimates (telephony + model inference), not exact billing.
    ai_cost_per_call_usd: float = 0.45  # blended cost of one AI voice call
    ai_cost_per_sms_usd: float = 0.03  # blended cost of one outbound AI SMS

    # Demo landing page
    demo_workspace_id: str = ""  # Workspace ID for demo requests
    demo_agent_id: str = ""  # Agent ID for demo requests
    demo_from_phone_number: str = ""  # Phone number to send demo calls/texts from
    demo_ip_rate_limit: int = 15  # Max requests per IP per hour
    demo_phone_rate_limit: int = 9  # Max requests per phone per day
    # Dev phones that skip rate limits (opt-in via env DEMO_RATE_LIMIT_BYPASS_PHONES)
    demo_rate_limit_bypass_phones: list[str] = []

    # Stripe
    stripe_secret_key: str = ""
    stripe_publishable_key: str = ""
    stripe_price_id: str = ""  # Monthly subscription price ID
    stripe_webhook_secret: str = ""

    # Lead form
    lead_form_ip_rate_limit: int = 20  # Max submissions per IP per hour

    # Security - Trusted Proxies
    trusted_proxies: list[str] = ["127.0.0.1", "::1"]  # IPs allowed to set X-Forwarded-For

    # Sentry — error tracking & performance monitoring. Leave DSN unset to disable.
    sentry_dsn: str | None = None

    # Prometheus metrics — shared-secret token required to scrape /metrics.
    # Leave empty to disable the endpoint entirely (returns 503). Set in Railway
    # to a strong random value (e.g. `openssl rand -hex 32`) and configure your
    # scraper with `Authorization: Bearer <metrics_token>`.
    metrics_token: str = ""

    # WebSocket connection limits (backpressure)
    # ``voice_bridge_max_connections`` caps total concurrent Telnyx voice bridge
    # sockets; new arrivals get WS_1013 (try again later) once the semaphore is
    # full. ``voice_test_max_connections`` does the same for the browser test
    # endpoint, which is much lower-volume.
    voice_bridge_max_connections: int = 100
    voice_test_max_connections: int = 20
    # Per-workspace cap on concurrent voice sessions (any endpoint). Tracked in
    # Redis so the limit holds across multiple backend replicas.
    voice_workspace_max_sessions: int = 10
    # Heartbeat — send {"type":"ping"} every N seconds, close the socket if no
    # pong is received within ``voice_pong_timeout_seconds``.
    voice_heartbeat_interval_seconds: int = 20
    voice_pong_timeout_seconds: int = 40
    # Absolute backstop on call duration. Even if the heartbeat and per-tenant
    # limits don't catch a runaway session, this guarantees we close the socket
    # after N seconds.
    voice_max_call_duration_seconds: int = 30 * 60

    # Live (during-call) sentiment scoring + escalation. When enabled, the voice
    # bridge scores the caller's transcript incrementally and, when negative
    # sentiment is *sustained*, emits an escalation event (operator push
    # notification + optional automatic human transfer). These are lightweight,
    # lexicon-based defaults; per-agent overrides are read from the agent config
    # at call time when present.
    voice_live_sentiment_enabled: bool = True
    # Smoothed score (EWMA) at/below which sustained negativity escalates.
    voice_sentiment_escalation_threshold: float = -0.4
    # Consecutive negative utterances required before escalation fires.
    voice_sentiment_sustained_turns: int = 3
    # EWMA smoothing factor in (0, 1]; higher reacts faster to the latest turn.
    voice_sentiment_smoothing: float = 0.5
    # When True, a sustained-negativity escalation also attempts an automatic
    # warm/cold human transfer (only if the agent has a transfer destination
    # configured). When False, escalation only notifies operators.
    voice_sentiment_auto_transfer: bool = False


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance.

    ``secret_key`` is required from the environment (no default), so the app
    refuses to boot without ``SECRET_KEY`` set. The ``type: ignore`` silences
    mypy's call-arg check — pydantic-settings populates required fields from
    env vars at instantiation, which mypy cannot see.
    """
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
