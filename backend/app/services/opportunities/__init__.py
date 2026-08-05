"""Opportunity service."""

from .default_pipeline import (
    DEFAULT_PIPELINE_NAME,
    DEFAULT_PIPELINE_STAGES,
    ensure_default_pipeline,
    get_default_pipeline_first_stage,
)
from .lead_opportunity import auto_pipeline_enabled, open_lead_opportunity
from .opportunity_service import OpportunityService
from .quote_opportunity import on_quote_sent_enabled, place_quote_on_pipeline

__all__ = [
    "DEFAULT_PIPELINE_NAME",
    "DEFAULT_PIPELINE_STAGES",
    "OpportunityService",
    "auto_pipeline_enabled",
    "ensure_default_pipeline",
    "get_default_pipeline_first_stage",
    "on_quote_sent_enabled",
    "open_lead_opportunity",
    "place_quote_on_pipeline",
]
