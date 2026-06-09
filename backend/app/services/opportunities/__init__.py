"""Opportunity service."""

from .default_pipeline import (
    DEFAULT_PIPELINE_NAME,
    DEFAULT_PIPELINE_STAGES,
    ensure_default_pipeline,
)
from .opportunity_service import OpportunityService

__all__ = [
    "DEFAULT_PIPELINE_NAME",
    "DEFAULT_PIPELINE_STAGES",
    "OpportunityService",
    "ensure_default_pipeline",
]
