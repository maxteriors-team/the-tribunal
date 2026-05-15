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
    openai_timeout: int = 60

    # Telnyx
    telnyx_api_key: str = ""
    telnyx_webhook_secret: str = ""
    telnyx_public_key: str = ""
    skip_webhook_verification: bool = False
    # Telnyx Voice
    telnyx_connection_id: str = ""  # Required for outbound calls


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
