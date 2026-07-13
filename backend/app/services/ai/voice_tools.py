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

# End-call tool.
# Gives the phone agent a way to gracefully hang up once the conversation is
# genuinely over. Without it the agent can only fall silent, which leaves the
# caller in dead air until an idle timeout tears down the media stream. The
# execution layer speaks nothing itself: the model must deliver its farewell
# BEFORE calling this, and the hangup is delayed a few seconds so the goodbye
# audio finishes playing before the line drops.
END_CALL_TOOL: dict[str, Any] = {
    "type": "function",
    "name": "end_call",
    "description": (
        "End and hang up the current phone call. Use this ONLY when the "
        "conversation is genuinely complete \u2014 the caller has said goodbye, "
        "declined further help, or you have finished helping them and said your "
        "farewell. IMPORTANT: First say a short, warm goodbye out loud to the "
        "caller (for example 'Thanks for calling, have a great day!'). Then call "
        "this tool. Do NOT say anything after calling it \u2014 the line will hang "
        "up on its own a few seconds later. Never use this while the caller still "
        "needs help or is mid-sentence."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": (
                    "Brief reason the call is ending, for logging only "
                    "(e.g. 'caller said goodbye', 'not interested', "
                    "'finished booking'). Not spoken to the caller."
                ),
            },
        },
        "required": [],
    },
}

# Live transfer / handoff tool.
# Lets the AI hand the active call to a human closer when the caller asks for a
# human or qualifies as a hot lead. The execution layer resolves warm vs cold
# mode and the destination number from agent/workspace config, so the model
# only needs to declare *why* it's transferring (intent + short context).
TRANSFER_CALL_TOOL: dict[str, Any] = {
    "type": "function",
    "name": "transfer_call",
    "description": (
        "Transfer (hand off) the current live phone call to a human closer. "
        "Call this ONLY when the caller explicitly asks to speak to a human, "
        "is frustrated, or clearly qualifies as a hot lead that a person should "
        "close now. The destination number and whether the human hears a spoken "
        "briefing first (warm) or is connected immediately (cold) are configured "
        "by the operator \u2014 you do NOT choose the number. "
        "After you call this tool, briefly tell the caller you're connecting them "
        "to a team member, then stop talking and WAIT \u2014 do not keep "
        "conversing, the call is being handed off."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": (
                    "Short reason for the handoff, e.g. 'caller asked for a human', "
                    "'hot lead ready to buy', or 'frustrated about billing'."
                ),
            },
            "intent": {
                "type": "string",
                "description": (
                    "One short phrase describing what the caller wants \u2014 spoken "
                    "to the human in warm mode (e.g. 'wants pricing on the premium plan')."
                ),
            },
            "summary": {
                "type": "string",
                "description": (
                    "Optional 1\u20132 sentence briefing of key facts for the human "
                    "closer (caller's situation, name, any numbers already discussed). "
                    "Used only in warm mode."
                ),
            },
        },
        "required": ["reason"],
    },
}

# On-demand knowledge retrieval tool.
# Replaces static prompt-stuffing (the old ~4k-token CAG concat): instead of
# dumping the whole knowledge base into the system prompt, the agent calls this
# tool to pull only the passages it needs for the current question. Execution
# runs hybrid (vector + keyword) retrieval scoped to the call's workspace + agent.
SEARCH_KNOWLEDGE_TOOL: dict[str, Any] = {
    "type": "function",
    "name": "search_knowledge",
    "description": (
        "Search this business's knowledge base for facts you need to answer the "
        "caller accurately \u2014 pricing, policies, FAQs, hours, product details, "
        "or anything specific to this company. Call this BEFORE answering any "
        "factual question instead of guessing. Pass a focused natural-language "
        "query describing what you need to know. Returns ranked passages with the "
        "document title each came from; ground your answer in those passages and "
        "do NOT invent details that are not returned."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "What you need to find out, phrased as a focused question or "
                    "keywords (e.g. 'cancellation policy for monthly plan', "
                    "'weekend opening hours')."
                ),
            },
            "top_k": {
                "type": "integer",
                "description": (
                    "Optional number of passages to retrieve (1-10). Defaults to 5. "
                    "Ask for more only when a broad question needs several sources."
                ),
            },
        },
        "required": ["query"],
    },
}

# Read-only caller account lookup tool.
# Lets the receptionist answer account-specific questions about the *current
# caller* ("when's my appointment?", "what's my status?") by reading only that
# caller's own CRM record. Execution is strictly read-only and hard-scoped to the
# call's workspace + resolved contact, so it can never read another tenant's or
# another person's data. Takes no arguments — the caller is implicit (the active
# call), so the model cannot point it at a different contact.
LOOKUP_CALLER_RECORD_TOOL: dict[str, Any] = {
    "type": "function",
    "name": "lookup_caller_record",
    "description": (
        "Look up the CURRENT caller's own account record to answer questions "
        "about THEIR appointments, status, or deals — e.g. 'when is my "
        "appointment?', 'what's my status?', 'do I have anything booked?'. "
        "Returns the caller's upcoming appointments, open opportunities/deals, "
        "contact status and notes, and a short summary of the last interaction. "
        "This is READ-ONLY and only ever returns THIS caller's record — you "
        "cannot look up anyone else. If the caller is not recognized it returns "
        "no record; in that case, do NOT invent details — offer to take their "
        "information instead. Takes no arguments."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
    },
}

# "Take a message" capture tool.
# Lets the receptionist capture a structured message for a human when the
# caller wants someone to call them back or to relay something — instead of
# transferring or booking. The execution layer persists the message and
# notifies operators (push + email). Opt-in via ``take_message`` in the agent's
# enabled_tools so it is only exposed on receptionist-style agents.
TAKE_MESSAGE_TOOL: dict[str, Any] = {
    "type": "function",
    "name": "take_message",
    "description": (
        "Take a message for a human team member when the caller wants someone to "
        "call them back or to relay information — and you cannot resolve it "
        "yourself or transfer/book. Collect as much structure as the caller will "
        "give: their name, the best callback number, the reason/topic, how urgent "
        "it is, when they'd prefer to be called back, and the message itself. "
        "Confirm the callback number back to the caller before sending. Call this "
        "ONCE you have gathered the details; the team is notified immediately. "
        "Do not invent details the caller did not give — leave fields out instead."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "caller_name": {
                "type": "string",
                "description": "The caller's name (who the message is from).",
            },
            "callback_number": {
                "type": "string",
                "description": (
                    "The best phone number to call the caller back on. Read it "
                    "back to confirm before sending."
                ),
            },
            "reason": {
                "type": "string",
                "description": (
                    "Short reason or topic for the message (e.g. 'billing "
                    "question', 'wants a quote', 'following up on order')."
                ),
            },
            "urgency": {
                "type": "string",
                "enum": ["low", "medium", "high"],
                "description": (
                    "How urgent the callback is. Use 'high' only when the caller "
                    "says it's urgent/time-sensitive."
                ),
            },
            "preferred_callback_time": {
                "type": "string",
                "description": (
                    "When the caller would prefer to be called back, in their own "
                    "words (e.g. 'tomorrow afternoon', 'after 5pm', 'anytime')."
                ),
            },
            "message": {
                "type": "string",
                "description": "The full free-text message the caller wants relayed.",
            },
        },
        "required": ["message"],
    },
}

# Save-lead-info tool.
# Lets the agent write structured details the caller volunteers (name, email,
# company, address, what they're looking for) onto the caller's CRM contact
# record, creating the contact from the caller's phone number if they are not
# already in the CRM. Without this, spoken lead details only survive as a
# free-text message note and never populate the contact profile. Opt-in via
# ``save_lead_info`` (or the existing ``crm_update`` intent) in enabled_tools.
SAVE_LEAD_INFO_TOOL: dict[str, Any] = {
    "type": "function",
    "name": "save_lead_info",
    "description": (
        "Save details the CURRENT caller gives you about themselves onto their "
        "contact record in the CRM. Call this whenever the caller shares their "
        "name, email, company, mailing address, or what they're looking for, so "
        "the team has it after the call. You can call it more than once as new "
        "details come up. Only include fields the caller actually gave you \u2014 "
        "never guess or invent an email, address, or name. Read an email or "
        "address back to the caller to confirm before saving it."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "first_name": {
                "type": "string",
                "description": "The caller's first name.",
            },
            "last_name": {
                "type": "string",
                "description": "The caller's last name.",
            },
            "email": {
                "type": "string",
                "description": (
                    "The caller's email address. Read it back to confirm spelling before saving."
                ),
            },
            "company_name": {
                "type": "string",
                "description": "The caller's company or business name.",
            },
            "address": {
                "type": "string",
                "description": (
                    "The caller's mailing or property address in their own words "
                    "(e.g. '123 Main St, Austin TX 78701')."
                ),
            },
            "interest": {
                "type": "string",
                "description": (
                    "Short summary of what the caller wants or is interested in "
                    "(e.g. 'wants a quote for a kitchen remodel in April'). Saved "
                    "as a note on the contact."
                ),
            },
        },
        "required": [],
    },
}

# In-call payment / deposit collection tool.
# SECURE BY DESIGN: this NEVER reads raw card numbers over the AI channel. The
# execution layer creates a Stripe Checkout Session for the requested amount and
# texts the hosted payment link to the caller, recording payment intent/status
# against the contact/opportunity. Opt-in via ``collect_payment`` in the agent's
# enabled_tools so only agents authorized to take money expose it.
COLLECT_PAYMENT_TOOL: dict[str, Any] = {
    "type": "function",
    "name": "collect_payment",
    "description": (
        "Collect a payment or deposit from the CURRENT caller by texting them a "
        "secure payment link. Use this ONLY after the caller explicitly agrees to "
        "pay a specific amount (e.g. a booking deposit or invoice). "
        "NEVER ask the caller to read out their card number, CVV, or expiry — you "
        "do NOT take card details by voice. This tool sends a secure Stripe link "
        "by SMS to the caller's phone; they complete payment there. "
        "Confirm the amount and what it is for before calling this. After calling "
        "it, tell the caller to check their phone for the payment link, and use "
        "check_payment_status if they say they've paid."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "amount": {
                "type": "number",
                "description": (
                    "The amount to charge in the major currency unit (e.g. dollars). "
                    "For example 50 means $50.00. Must be a positive number you have "
                    "confirmed with the caller."
                ),
            },
            "description": {
                "type": "string",
                "description": (
                    "Short description of what the payment is for, e.g. "
                    "'booking deposit', 'invoice #1234'. Shown to the caller on the "
                    "payment page."
                ),
            },
            "currency": {
                "type": "string",
                "description": (
                    "Optional ISO 4217 currency code (e.g. 'usd', 'gbp'). "
                    "Defaults to USD when omitted."
                ),
            },
        },
        "required": ["amount"],
    },
}

# Companion read-only tool: lets the agent confirm whether the most recent
# in-call payment link has been paid yet. Read-only (no spend, no mutation of
# external state) so it is gate-exempt and safe to poll during the live call.
CHECK_PAYMENT_STATUS_TOOL: dict[str, Any] = {
    "type": "function",
    "name": "check_payment_status",
    "description": (
        "Check whether the payment link you just texted the CURRENT caller has "
        "been paid. Call this when the caller says they have completed (or are "
        "having trouble with) the payment. Takes no arguments — it checks this "
        "call's most recent payment request. Do not invent a result; report only "
        "what this tool returns."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
    },
}

APPLICATION_LINK_SMS_TOOL: dict[str, Any] = {
    "type": "function",
    "name": "send_application_link",
    "description": (
        "Send the fixed Prestyj founding cohort application link by SMS to the current caller. "
        "Use only after the person explicitly agrees to receive the link. The SMS body is fixed; "
        "do not use this for general texting, custom follow-ups, or unrelated links."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
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
                "skill": {
                    "type": "string",
                    "description": (
                        "Optional skill, specialty, or service the appointment needs "
                        "(e.g. 'spanish', 'mortgage', 'new car sales'). When set, the "
                        "system routes the booking to an available staff member who has "
                        "that skill. Only pass this if the caller's need clearly maps to "
                        "a specialty; otherwise leave it out."
                    ),
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
                "skill": {
                    "type": "string",
                    "description": (
                        "Optional skill/specialty needed; restricts availability to "
                        "staff with that skill when skill-based routing is enabled."
                    ),
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
                    "skill": {
                        "type": "string",
                        "description": (
                            "Optional skill/specialty needed; restricts availability to "
                            "staff with that skill when skill-based routing is enabled."
                        ),
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
    enable_application_link_sms: bool = False,
    enable_transfer: bool = False,
    enable_search_knowledge: bool = False,
    enable_lookup_caller_record: bool = False,
    enable_take_message: bool = False,
    enable_collect_payment: bool = False,
    enable_save_lead_info: bool = False,
    enable_end_call: bool = True,
    timezone: str = "America/New_York",
) -> list[dict[str, Any]]:
    """Build a complete tools list based on enabled features.

    Args:
        enable_booking: Include Cal.com booking tools
        enable_web_search: Include Grok web search tool
        enable_x_search: Include Grok X/Twitter search tool
        enable_dtmf: Include DTMF tool for IVR navigation
        enable_application_link_sms: Include fixed Prestyj application-link SMS tool
        enable_transfer: Include live human transfer/handoff tool
        enable_search_knowledge: Include the on-demand knowledge retrieval tool
        enable_lookup_caller_record: Include the read-only caller record lookup tool
        enable_take_message: Include the "take a message" capture tool
        enable_collect_payment: Include the in-call payment/deposit collection tool
        enable_end_call: Include the graceful end-call/hangup tool (on by default;
            every voice agent should be able to hang up when a call is over)
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

    # On-demand knowledge retrieval (replaces static CAG prompt-stuffing)
    if enable_search_knowledge:
        tools.append(SEARCH_KNOWLEDGE_TOOL)

    # Read-only lookup of the current caller's own CRM record
    if enable_lookup_caller_record:
        tools.append(LOOKUP_CALLER_RECORD_TOOL)

    # Structured "take a message" capture for operator follow-up
    if enable_take_message:
        tools.append(TAKE_MESSAGE_TOOL)

    # In-call payment / deposit collection (secure SMS link + status check)
    if enable_collect_payment:
        tools.append(COLLECT_PAYMENT_TOOL)
        tools.append(CHECK_PAYMENT_STATUS_TOOL)

    # Write caller-provided lead details onto the CRM contact record
    if enable_save_lead_info:
        tools.append(SAVE_LEAD_INFO_TOOL)

    # DTMF for IVR
    if enable_dtmf:
        tools.append(DTMF_TOOL)

    # Live human transfer / handoff
    if enable_transfer:
        tools.append(TRANSFER_CALL_TOOL)

    # Fixed Prestyj application-link SMS
    if enable_application_link_sms:
        tools.append(APPLICATION_LINK_SMS_TOOL)

    # Graceful hang-up once the conversation is over
    if enable_end_call:
        tools.append(END_CALL_TOOL)

    # Booking tools with date context
    if enable_booking:
        tools.extend(get_booking_tools(timezone))

    return tools


def is_transfer_enabled(agent: Any) -> bool:
    """Return whether the live transfer/handoff tool should be exposed.

    Transfer is opt-in: the agent must enable it (either a direct
    ``"transfer_call"`` entry in ``enabled_tools`` or the integration-based
    ``call_control`` + ``transfer_call`` pattern) AND have a destination number
    resolvable (per-agent ``transfer_destination_number`` here; the executor
    additionally falls back to workspace settings at call time).
    """
    if not agent:
        return False

    enabled_tools = agent.enabled_tools or []
    tool_settings = agent.tool_settings or {}
    call_control_tools = tool_settings.get("call_control", []) or []
    return "transfer_call" in enabled_tools or (
        "call_control" in enabled_tools and "transfer_call" in call_control_tools
    )


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

    # This is intentionally opt-in. The function sends a fixed Prestyj link,
    # so a generic "twilio_send_sms" setting must not expose it to every agent.
    twilio_sms_tools = tool_settings.get("twilio-sms", []) or []
    application_link_sms_enabled = "send_application_link" in enabled_tools or (
        "twilio-sms" in enabled_tools and "send_application_link" in twilio_sms_tools
    )

    return build_tools_list(
        enable_booking=enable_booking,
        enable_web_search="web_search" in enabled_tools,
        enable_x_search="x_search" in enabled_tools,
        enable_dtmf=dtmf_enabled,
        enable_application_link_sms=application_link_sms_enabled,
        enable_transfer=is_transfer_enabled(agent),
        enable_search_knowledge=is_search_knowledge_enabled(agent),
        enable_lookup_caller_record=is_lookup_caller_record_enabled(agent),
        enable_take_message=is_take_message_enabled(agent),
        enable_collect_payment=is_collect_payment_enabled(agent),
        enable_save_lead_info=is_save_lead_info_enabled(agent),
        timezone=timezone,
    )


def is_search_knowledge_enabled(agent: Any) -> bool:
    """Return whether the on-demand knowledge retrieval tool should be exposed.

    Opt-in via ``"search_knowledge"`` in the agent's ``enabled_tools``. The tool
    is only useful when the agent has an ingested knowledge base, so operators
    enable it explicitly rather than paying the per-turn tool overhead always.
    """
    if not agent:
        return False
    return "search_knowledge" in (agent.enabled_tools or [])


def is_lookup_caller_record_enabled(agent: Any) -> bool:
    """Return whether the read-only caller record lookup tool should be exposed.

    Opt-in via ``"lookup_caller_record"`` in the agent's ``enabled_tools``. The
    tool reads the caller's own CRM record (appointments, deals, status), so
    operators enable it explicitly for receptionist-style agents rather than
    exposing account data on every agent by default.
    """
    if not agent:
        return False
    return "lookup_caller_record" in (agent.enabled_tools or [])


def is_collect_payment_enabled(agent: Any) -> bool:
    """Return whether the in-call payment/deposit collection tool should be exposed.

    Opt-in via ``"collect_payment"`` in the agent's ``enabled_tools``. The tool
    initiates real money movement (a Stripe payment link texted to the caller),
    so it is enabled explicitly for agents authorized to take payments rather
    than exposed on every agent by default.
    """
    if not agent:
        return False
    return "collect_payment" in (agent.enabled_tools or [])


def is_take_message_enabled(agent: Any) -> bool:
    """Return whether the "take a message" capture tool should be exposed.

    Opt-in via ``"take_message"`` in the agent's ``enabled_tools``. The tool
    persists a structured message and notifies operators, so it is enabled
    explicitly for receptionist-style agents rather than on every agent.
    """
    if not agent:
        return False
    return "take_message" in (agent.enabled_tools or [])


def is_save_lead_info_enabled(agent: Any) -> bool:
    """Return whether the save-lead-info CRM write tool should be exposed.

    Opt-in via ``"save_lead_info"`` in the agent's ``enabled_tools``, or the
    pre-existing ``"crm_update"`` intent already declared on lead-responder
    templates. The tool writes/creates a CRM contact, so it is enabled
    explicitly for lead-capturing agents rather than on every agent.
    """
    if not agent:
        return False
    enabled_tools = agent.enabled_tools or []
    return "save_lead_info" in enabled_tools or "crm_update" in enabled_tools


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
def get_text_search_knowledge_tool() -> dict[str, Any]:
    """Knowledge retrieval tool in OpenAI function-calling format for text agents.

    Mirrors :data:`SEARCH_KNOWLEDGE_TOOL` but wrapped in the
    ``{"type": "function", "function": {...}}`` shape the chat completions API
    expects. Lets the text/SMS agent pull only the passages it needs instead of
    static prompt-stuffing the full knowledge base.
    """
    return {
        "type": "function",
        "function": {
            "name": SEARCH_KNOWLEDGE_TOOL["name"],
            "description": SEARCH_KNOWLEDGE_TOOL["description"],
            "parameters": SEARCH_KNOWLEDGE_TOOL["parameters"],
        },
    }


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
                        "skill": {
                            "type": "string",
                            "description": (
                                "Optional skill, specialty, or service the appointment "
                                "needs (e.g. 'spanish', 'mortgage'). When set, routes the "
                                "booking to a staff member with that skill. Leave out "
                                "unless the need clearly maps to a specialty."
                            ),
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
                        "skill": {
                            "type": "string",
                            "description": (
                                "Optional skill/specialty needed; restricts availability "
                                "to staff with that skill when skill-based routing is on."
                            ),
                        },
                    },
                    "required": ["start_date"],
                },
            },
        },
    ]
