"""CRM assistant tool definitions for OpenAI function calling.

Style: short imperative descriptions, only non-obvious params documented.
Mirrors the prompt-hint style in ezcoder's tools/prompt-hints.ts.
"""

from copy import deepcopy
from typing import Any

from app.services.ai.crm_assistant._tool_metadata import get_tool_policy

CONFIRMED_PARAM = {
    "type": "boolean",
    "description": "True only after explicit user confirmation",
}


def _with_confirmation_property(tool: dict[str, Any]) -> dict[str, Any]:
    """Add the confirmation parameter when tool metadata requires it."""

    function = tool["function"]
    if not get_tool_policy(function["name"]).requires_confirmation:
        return tool
    properties = function.setdefault("parameters", {}).setdefault("properties", {})
    properties.setdefault("confirmed", CONFIRMED_PARAM)
    return tool


def _apply_tool_policy_metadata(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return OpenAI tool definitions augmented from CRM tool metadata."""

    return [_with_confirmation_property(deepcopy(tool)) for tool in tools]


CRM_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_contacts",
            "description": "Search contacts by name, phone, email, or company.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search term"},
                    "limit": {"type": "integer", "description": "Max results (default 10)"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_contact",
            "description": "Create a new contact. Requires first_name + phone in E.164.",
            "parameters": {
                "type": "object",
                "properties": {
                    "first_name": {"type": "string"},
                    "last_name": {"type": "string"},
                    "phone": {"type": "string", "description": "E.164 format (+15551234567)"},
                    "email": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["first_name", "phone"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_campaigns",
            "description": "List campaigns. Filter by status if provided.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "description": (
                            "draft | scheduled | running | paused | completed | canceled"
                        ),
                    },
                    "limit": {"type": "integer", "description": "Max results (default 10)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_agents",
            "description": "List AI agents in the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Max results (default 10)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_sms",
            "description": "Send an SMS to a contact by id. Confirm with the user first "
            "unless they already gave a clear directive.",
            "parameters": {
                "type": "object",
                "properties": {
                    "contact_id": {"type": "integer"},
                    "body": {"type": "string", "description": "Message text"},
                },
                "required": ["contact_id", "body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_initial_message",
            "description": (
                "Send a campaign's initial message to one contact. Requires explicit confirmation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "campaign_id": {"type": "string", "description": "Campaign UUID"},
                    "contact_id": {"type": "integer"},
                },
                "required": ["campaign_id", "contact_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "start_campaign",
            "description": (
                "Start a draft, paused, or scheduled campaign. This can send messages or calls; "
                "requires explicit user confirmation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "campaign_id": {"type": "string", "description": "Campaign UUID"},
                },
                "required": ["campaign_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pause_campaign",
            "description": "Pause a running campaign. Does not send messages or calls.",
            "parameters": {
                "type": "object",
                "properties": {
                    "campaign_id": {"type": "string", "description": "Campaign UUID"},
                },
                "required": ["campaign_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resume_campaign",
            "description": (
                "Resume a paused campaign. This can immediately send messages or calls; "
                "requires explicit user confirmation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "campaign_id": {"type": "string", "description": "Campaign UUID"},
                },
                "required": ["campaign_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "summarize_campaign",
            "description": "Summarize campaign status, delivery, replies, appointments, and rates.",
            "parameters": {
                "type": "object",
                "properties": {
                    "campaign_id": {"type": "string", "description": "Campaign UUID"},
                },
                "required": ["campaign_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "plan_outbound_growth_workflow",
            "description": (
                "Turn a high-level outbound intent into offer/segment selection, campaign copy, "
                "sample previews, a draft campaign, responder recommendation, "
                "and next approval step."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "intent": {
                        "type": "string",
                        "description": "User's outbound goal in plain English",
                    },
                    "offer_id": {
                        "type": "string",
                        "description": "Offer UUID, if already chosen",
                    },
                    "segment_id": {
                        "type": "string",
                        "description": "Segment UUID, if already chosen",
                    },
                    "from_phone_number": {
                        "type": "string",
                        "description": "Sending phone number in E.164",
                    },
                    "create_draft": {
                        "type": "boolean",
                        "description": "Create draft campaign now (default true)",
                    },
                    "create_responder_agent": {
                        "type": "boolean",
                        "description": (
                            "Create inactive responder draft if no active responder exists"
                        ),
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_agent",
            "description": "Create a new AI agent. Requires explicit confirmation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "channel_mode": {"type": "string", "description": "voice | text | both"},
                    "voice_provider": {"type": "string", "description": "openai | elevenlabs"},
                    "voice_id": {"type": "string"},
                    "language": {"type": "string"},
                    "system_prompt": {"type": "string"},
                    "temperature": {"type": "number"},
                    "enabled_tools": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name", "system_prompt"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_agent",
            "description": "Update an existing AI agent. Requires explicit confirmation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "Agent UUID"},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "channel_mode": {"type": "string", "description": "voice | text | both"},
                    "system_prompt": {"type": "string"},
                    "temperature": {"type": "number"},
                    "is_active": {"type": "boolean"},
                    "enabled_tools": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["agent_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "assign_ai_responder",
            "description": (
                "Assign an AI agent to respond in a conversation. Requires explicit confirmation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "conversation_id": {"type": "string", "description": "Conversation UUID"},
                    "agent_id": {"type": "string", "description": "Agent UUID"},
                    "ai_enabled": {"type": "boolean"},
                },
                "required": ["conversation_id", "agent_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_conversation",
            "description": "Read recent messages with a contact.",
            "parameters": {
                "type": "object",
                "properties": {
                    "contact_id": {"type": "integer"},
                    "limit": {"type": "integer", "description": "Recent messages (default 20)"},
                },
                "required": ["contact_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_recent_conversations",
            "description": "Show recent conversations across all contacts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Max results (default 10)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_appointments",
            "description": "Show upcoming appointments.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Max results (default 10)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_dashboard_stats",
            "description": "Current totals: contacts, campaigns, conversations, "
            "upcoming appointments.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_today_queue",
            "description": "Today's ordered mission queue: pending approvals, nudges due "
            "today, fresh ad-library prospect batches, draft campaigns awaiting launch, "
            "and setup gaps. Use for morning briefings and 'what should I do today?'.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_opportunities",
            "description": "Pipeline opportunities/deals.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Max results (default 10)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_offers",
            "description": "List offer drafts and active offers for outbound campaigns.",
            "parameters": {
                "type": "object",
                "properties": {
                    "active_only": {"type": "boolean", "description": "Only return active offers"},
                    "limit": {"type": "integer", "description": "Max results (default 10)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_offer_details",
            "description": "Get full offer details for campaign messaging or review.",
            "parameters": {
                "type": "object",
                "properties": {
                    "offer_id": {"type": "string", "description": "Offer UUID"},
                },
                "required": ["offer_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_offer_draft",
            "description": "Create an inactive offer draft suitable for outbound campaign copy.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "discount_type": {
                        "type": "string",
                        "description": "percentage | fixed | free_service",
                    },
                    "discount_value": {"type": "number"},
                    "terms": {"type": "string"},
                    "headline": {"type": "string"},
                    "subheadline": {"type": "string"},
                    "regular_price": {"type": "number"},
                    "offer_price": {"type": "number"},
                    "savings_amount": {"type": "number"},
                    "guarantee_type": {
                        "type": "string",
                        "description": "money_back | satisfaction | results",
                    },
                    "guarantee_days": {"type": "integer"},
                    "guarantee_text": {"type": "string"},
                    "urgency_type": {
                        "type": "string",
                        "description": "limited_time | limited_quantity | expiring",
                    },
                    "urgency_text": {"type": "string"},
                    "scarcity_count": {"type": "integer"},
                    "value_stack_items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "description": {"type": "string"},
                                "value": {"type": "number"},
                                "included": {"type": "boolean"},
                            },
                            "required": ["name", "value"],
                        },
                    },
                    "cta_text": {"type": "string"},
                    "cta_subtext": {"type": "string"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_offer_draft",
            "description": "Update an offer draft before attaching it to outbound campaigns.",
            "parameters": {
                "type": "object",
                "properties": {
                    "offer_id": {"type": "string", "description": "Offer UUID"},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "discount_type": {
                        "type": "string",
                        "description": "percentage | fixed | free_service",
                    },
                    "discount_value": {"type": "number"},
                    "terms": {"type": "string"},
                    "is_active": {"type": "boolean"},
                    "headline": {"type": "string"},
                    "subheadline": {"type": "string"},
                    "regular_price": {"type": "number"},
                    "offer_price": {"type": "number"},
                    "savings_amount": {"type": "number"},
                    "guarantee_type": {
                        "type": "string",
                        "description": "money_back | satisfaction | results",
                    },
                    "guarantee_days": {"type": "integer"},
                    "guarantee_text": {"type": "string"},
                    "urgency_type": {
                        "type": "string",
                        "description": "limited_time | limited_quantity | expiring",
                    },
                    "urgency_text": {"type": "string"},
                    "scarcity_count": {"type": "integer"},
                    "value_stack_items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "description": {"type": "string"},
                                "value": {"type": "number"},
                                "included": {"type": "boolean"},
                            },
                            "required": ["name", "value"],
                        },
                    },
                    "cta_text": {"type": "string"},
                    "cta_subtext": {"type": "string"},
                },
                "required": ["offer_id"],
            },
        },
    },
]


def get_crm_tools() -> list[dict[str, Any]]:
    """Return the CRM tool definitions for OpenAI function calling."""
    return _apply_tool_policy_metadata(CRM_TOOLS)
