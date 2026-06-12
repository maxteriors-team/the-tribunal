"""Agent service."""

from .agent_service import AgentService
from .default_agent import ensure_default_agent
from .templates import (
    PRESTYJ_COLD_LEAD_RESPONDER_PROMPT,
    PRESTYJ_COLD_LEAD_RESPONDER_TEMPLATE_ID,
    build_prestyj_cold_lead_responder_template,
)

__all__ = [
    "AgentService",
    "PRESTYJ_COLD_LEAD_RESPONDER_PROMPT",
    "PRESTYJ_COLD_LEAD_RESPONDER_TEMPLATE_ID",
    "build_prestyj_cold_lead_responder_template",
    "ensure_default_agent",
]
