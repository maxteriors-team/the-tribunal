"""CRM assistant tool definitions for OpenAI function calling.

Style: short imperative descriptions, only non-obvious params documented.
Mirrors the prompt-hint style in ezcoder's tools/prompt-hints.ts.
"""

from typing import Any

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
                        "description": "draft | active | paused | completed",
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
]


def get_crm_tools() -> list[dict[str, Any]]:
    """Return the CRM tool definitions for OpenAI function calling."""
    return CRM_TOOLS
