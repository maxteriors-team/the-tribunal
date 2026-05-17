"""Voice agent tool definitions.

This module consolidates tool definitions that were previously scattered
across multiple voice agent implementations. Provides:
- DTMF tool for IVR navigation
- Cal.com booking tools with dynamic date context
- Grok built-in tools (web_search, x_search)

Usage:
    from app.services.ai.voice_tools import get_booking_tools, DTMF_TOOL

    tools = get_booking_tools(timezone="America/New_York")
    if dtmf_enabled:
        tools.append(DTMF_TOOL)
"""

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog

logger = structlog.get_logger()

# Grok built-in tools - these execute automatically on the provider side
GROK_BUILTIN_TOOLS: dict[str, dict[str, str]] = {
    "web_search": {
        "type": "web_search",
    },
    "x_search": {
        "type": "x_search",
    },
}

# DTMF tool for IVR menu navigation
# Allows AI agent to send touch-tone digits during calls
DTMF_TOOL: dict[str, Any] = {
    "type": "function",
    "name": "send_dtmf",
    "description": (
        "Send DTMF touch-tone digits to navigate automated phone menus (IVR systems). "
        "CRITICAL: When you hear 'Press 1 for X, Press 2 for Y', you MUST use this tool "
        "to send the appropriate digit - do NOT speak to the machine. "
        "Choose the menu option that best matches your goal (e.g., '2' for 'new car sales'). "
        "If the menu option for your goal isn't clear, try options 1-9 systematically. "
        "Only try '0' or '#' as a last resort after other options have failed. "
        "After sending DTMF, WAIT SILENTLY for either another menu or a human to answer. "
        "Only speak when a real human responds to you."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "digits": {
                "type": "string",
                "description": (
                    "The digit(s) to press. MUST include at least one digit (0-9, *, #). "
                    "Examples: '1' (press 1), '2' (press 2), '0' (operator), '#' (pound key). "
                    "For multiple digits with pauses: '1w2' (press 1, wait 0.5s, press 2). "
                    "IMPORTANT: Do not send only 'w' - always include actual digits."
                ),
            },
        },
        "required": ["digits"],
    },
}

# Static booking tool definitions (without date context)
# Use get_booking_tools() for tools with embedded date context
VOICE_BOOKING_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "book_appointment",
        "description": (
            "Book an appointment/meeting with the customer on Cal.com. "
            "Use this when the customer agrees to schedule a call, meeting, "
            "or appointment. You MUST collect the customer's email address first."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Appointment date in YYYY-MM-DD format",
                },
                "time": {
                    "type": "string",
                    "description": (
                        "Appointment time in HH:MM 24-hour format "
                        "(e.g., '14:00' for 2 PM, '09:30' for 9:30 AM). "
                        "Always pass 24-hour format here even though you "
                        "speak 12-hour format to the customer."
                    ),
                },
                "email": {
                    "type": "string",
                    "description": "Customer's email address for booking confirmation",
                },
                "duration_minutes": {
                    "type": "integer",
                    "description": "Duration in minutes. Default is 30.",
                },
                "notes": {
                    "type": "string",
                    "description": "Optional notes about the appointment",
                },
            },
            "required": ["date", "time", "email"],
        },
    },
    {
        "type": "function",
        "name": "check_availability",
        "description": (
            "Check available time slots on Cal.com for a date range. "
            "Use before booking to confirm slot availability."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD (defaults to start)",
                },
            },
            "required": ["start_date"],
        },
    },
]


def get_booking_tools(timezone: str = "America/New_York") -> list[dict[str, Any]]:
    """Generate booking tools with current date context embedded.

    The date context helps the LLM correctly interpret relative dates
    like "tomorrow" or "Friday" by providing the actual current date
    in the tool descriptions.

    Args:
        timezone: Timezone for date context (IANA format)

    Returns:
        List of tool definitions with embedded date context
    """
    try:
        tz = ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        logger.debug("invalid_timezone_fallback", timezone=timezone)
        tz = ZoneInfo("America/New_York")

    now = datetime.now(tz)
    today_str = now.strftime("%A, %B %d, %Y")
    today_iso = now.strftime("%Y-%m-%d")

    return [
        {
            "type": "function",
            "name": "book_appointment",
            "description": (
                f"Book an appointment on Cal.com. TODAY IS {today_str} ({today_iso}). "
                f"When converting relative dates to YYYY-MM-DD: 'today' = {today_iso}, "
                "'tomorrow' = the day after today, 'Friday' = the NEXT Friday from today. "
                "You MUST collect the customer's email address first."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": (
                            f"Appointment date in YYYY-MM-DD format. "
                            f"TODAY IS {today_iso}. Convert relative dates from this date."
                        ),
                    },
                    "time": {
                        "type": "string",
                        "description": (
                            "Appointment time in HH:MM 24-hour format "
                            "(e.g., '14:00' for 2 PM, '09:30' for 9:30 AM). "
                            "Always pass 24-hour format here even though you "
                            "speak 12-hour format to the customer."
                        ),
                    },
                    "email": {
                        "type": "string",
                        "description": "Customer's email address for booking confirmation",
                    },
                    "duration_minutes": {
                        "type": "integer",
                        "description": "Duration in minutes. Default is 30.",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Optional notes about the appointment",
                    },
                },
                "required": ["date", "time", "email"],
            },
        },
        {
            "type": "function",
            "name": "check_availability",
            "description": (
                f"Check available time slots on Cal.com. "
                f"TODAY IS {today_str} ({today_iso}). "
                f"When the user says 'Friday', 'tomorrow', or 'next week', "
                f"convert to YYYY-MM-DD relative to today ({today_iso}). "
                f"Example: if today is {today_iso} and user says 'Friday', "
                "calculate the next Friday from this date."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {
                        "type": "string",
                        "description": (
                            f"Start date in YYYY-MM-DD format. TODAY IS {today_iso}. "
                            "Convert relative dates like 'Friday' from this date."
                        ),
                    },
                    "end_date": {
                        "type": "string",
                        "description": "End date in YYYY-MM-DD (defaults to start_date)",
                    },
                },
                "required": ["start_date"],
            },
        },
    ]


def build_tools_list(
    *,
    enable_booking: bool = False,
    enable_web_search: bool = False,
    enable_x_search: bool = False,
    enable_dtmf: bool = False,
    timezone: str = "America/New_York",
) -> list[dict[str, Any]]:
    """Build a complete tools list based on enabled features.

    Args:
        enable_booking: Include Cal.com booking tools
        enable_web_search: Include Grok web search tool
        enable_x_search: Include Grok X/Twitter search tool
        enable_dtmf: Include DTMF tool for IVR navigation
        timezone: Timezone for booking tools date context

    Returns:
        List of tool definitions for session configuration
    """
    tools: list[dict[str, Any]] = []

    # Built-in Grok tools
    if enable_web_search:
        tools.append(GROK_BUILTIN_TOOLS["web_search"])

    if enable_x_search:
        tools.append(GROK_BUILTIN_TOOLS["x_search"])

    # DTMF for IVR
    if enable_dtmf:
        tools.append(DTMF_TOOL)

    # Booking tools with date context
    if enable_booking:
        tools.extend(get_booking_tools(timezone))

    return tools


def get_tools_from_agent_config(
    agent: Any,
    *,
    enable_booking: bool = False,
    timezone: str = "America/New_York",
) -> list[dict[str, Any]]:
    """Build tools list from agent configuration.

    Reads the agent's enabled_tools and tool_settings to determine
    which tools to include.

    Args:
        agent: Agent model with enabled_tools and tool_settings
        enable_booking: Whether Cal.com booking is available
        timezone: Timezone for booking tools date context

    Returns:
        List of tool definitions
    """
    if not agent:
        return []

    enabled_tools = agent.enabled_tools or []
    tool_settings = agent.tool_settings or {}

    # Check for DTMF enablement
    # Supports both direct "send_dtmf" in enabled_tools (legacy)
    # and integration-based "call_control" with "send_dtmf" in tool_settings
    call_control_tools = tool_settings.get("call_control", []) or []
    dtmf_enabled = "send_dtmf" in enabled_tools or (
        "call_control" in enabled_tools and "send_dtmf" in call_control_tools
    )

    return build_tools_list(
        enable_booking=enable_booking,
        enable_web_search="web_search" in enabled_tools,
        enable_x_search="x_search" in enabled_tools,
        enable_dtmf=dtmf_enabled,
        timezone=timezone,
    )


# Grok available voices (for validation)
GROK_VOICES: dict[str, str] = {
    "ara": "Ara - Warm & friendly (female, default)",
    "rex": "Rex - Confident & clear (male)",
    "sal": "Sal - Smooth & balanced (neutral)",
    "eve": "Eve - Energetic & upbeat (female)",
    "leo": "Leo - Authoritative & strong (male)",
}


def validate_grok_voice(voice_id: str) -> str | None:
    """Validate and normalize a Grok voice ID.

    Args:
        voice_id: Voice ID to validate

    Returns:
        Capitalized voice name if valid, None if invalid
    """
    voice_lower = voice_id.lower()
    if voice_lower in GROK_VOICES:
        return voice_lower.capitalize()
    return None


# OpenAI function calling format (for text agents)
# These use the {"type": "function", "function": {...}} wrapper
def get_text_booking_tools(timezone: str = "America/New_York") -> list[dict[str, Any]]:
    """Get booking tools in OpenAI function calling format for text agents.

    Text agents use the OpenAI chat completions API which requires tools
    in the {"type": "function", "function": {...}} format.

    Args:
        timezone: Timezone for date context (IANA format)

    Returns:
        List of tool definitions in OpenAI function calling format
    """
    try:
        tz = ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        logger.debug("invalid_timezone_fallback", timezone=timezone)
        tz = ZoneInfo("America/New_York")

    now = datetime.now(tz)
    today_str = now.strftime("%A, %B %d, %Y")
    today_iso = now.strftime("%Y-%m-%d")

    return [
        {
            "type": "function",
            "function": {
                "name": "book_appointment",
                "description": (
                    f"Book an appointment/meeting with the customer on Cal.com. "
                    f"TODAY IS {today_str} ({today_iso}). "
                    f"Use this when the customer agrees to schedule a call, meeting, "
                    f"or appointment. Parse relative dates like 'tomorrow at 2pm'. "
                    f"IMPORTANT: You MUST collect the customer's email address and include "
                    f"it in this call. Ask for email in the same message as confirming the booking."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "date": {
                            "type": "string",
                            "description": (
                                f"Appointment date in YYYY-MM-DD format. TODAY IS {today_iso}."
                            ),
                        },
                        "time": {
                            "type": "string",
                            "description": (
                                "Appointment time in HH:MM 24-hour format "
                                "(e.g., '14:00' for 2 PM, '09:30' for 9:30 AM). "
                                "Always pass 24-hour format here even though you "
                                "speak 12-hour format to the customer."
                            ),
                        },
                        "email": {
                            "type": "string",
                            "description": (
                                "Customer's email address for booking confirmation. "
                                "REQUIRED - always ask for and include the email."
                            ),
                        },
                        "duration_minutes": {
                            "type": "integer",
                            "description": "Duration in minutes. Default is 30.",
                            "default": 30,
                        },
                        "notes": {
                            "type": "string",
                            "description": "Optional notes about the appointment",
                        },
                    },
                    "required": ["date", "time", "email"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "check_availability",
                "description": (
                    f"Check available time slots on Cal.com for a date range. "
                    f"TODAY IS {today_str} ({today_iso}). "
                    f"Use before booking to confirm slot availability."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "start_date": {
                            "type": "string",
                            "description": (
                                f"Start date in YYYY-MM-DD format. TODAY IS {today_iso}."
                            ),
                        },
                        "end_date": {
                            "type": "string",
                            "description": "End date in YYYY-MM-DD (defaults to start)",
                        },
                    },
                    "required": ["start_date"],
                },
            },
        },
    ]
