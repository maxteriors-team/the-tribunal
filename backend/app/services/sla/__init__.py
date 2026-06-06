"""Speed-to-lead SLA: first-response tracking, metrics, and proof badge."""

from app.services.sla.speed_to_lead import (
    DEFAULT_SLA_SECONDS,
    SETTINGS_KEY,
    SLAMetrics,
    SpeedToLeadSettings,
    compute_sla_metrics,
    get_speed_to_lead_settings,
    mark_inbound_lead,
    record_first_response,
    record_first_response_and_maybe_alert,
)

__all__ = [
    "DEFAULT_SLA_SECONDS",
    "SETTINGS_KEY",
    "SLAMetrics",
    "SpeedToLeadSettings",
    "compute_sla_metrics",
    "get_speed_to_lead_settings",
    "mark_inbound_lead",
    "record_first_response",
    "record_first_response_and_maybe_alert",
]
