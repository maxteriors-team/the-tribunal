"""CRM assistant service package."""

from app.services.ai.crm_assistant._processor import (
    process_assistant_message,
    stream_assistant_message,
)

__all__ = ["process_assistant_message", "stream_assistant_message"]
