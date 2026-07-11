"""CRM assistant service package."""

from app.services.ai.crm_assistant._processor import (
    enhance_assistant_prompt,
    process_assistant_message,
    stream_assistant_message,
)

__all__ = [
    "enhance_assistant_prompt",
    "process_assistant_message",
    "stream_assistant_message",
]
