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

    # OpenAI
    openai_api_key: str = ""
    openai_oauth_access_token: str = ""
    openai_oauth_refresh_token: str = ""
    openai_oauth_expires_at: int | None = None
    openai_oauth_account_id: str = ""
    openai_oauth_client_id: str = ""
    openai_oauth_redirect_uri: str = ""
    openai_oauth_token_url: str = "https://auth.openai.com/oauth/token"
    openai_realtime_model: str = "gpt-realtime-2"
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

    # ElevenLabs
    elevenlabs_api_key: str = ""

    # xAI (Grok)
    xai_api_key: str = ""

    # Resend
    resend_api_key: str = ""
    resend_from_email: str = "noreply@example.com"
    resend_from_name: str = "AI CRM"
    resend_webhook_secret: str = ""

    # Expo Push Notifications
    expo_access_token: str = ""

    # Google Places API
    google_places_api_key: str = ""

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
    cors_allow_vercel_previews: bool = True  # Allow *.vercel.app origins for preview deployments
    api_base_url: str = ""  # Base URL for webhooks (e.g., https://api.example.com)
    frontend_url: str = "http://localhost:3000"  # Frontend URL for links in emails
    public_base_url: str = "http://localhost:8000"  # Public base URL for short link redirects

    # Workers
    campaign_poll_interval: int = 5
    ai_response_delay_ms: int = 2000

    # Enrichment
    enable_ai_enrichment: bool = True  # Toggle AI website summary

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
