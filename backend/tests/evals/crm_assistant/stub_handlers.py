"""Canned tool results for the eval harness.

The eval scores tool *choice*, so handlers are stubbed: no DB, no telephony,
no workspace fixtures. Payloads mirror the real handlers' shape closely enough
that a multi-step chain (search → act) keeps unfolding instead of stalling on
an unparseable result.
"""

from __future__ import annotations

from typing import Any

_CONTACT = {
    "id": 512,
    "first_name": "Bob",
    "last_name": "Marchetti",
    "phone": "+15554829910",
    "email": "bob.marchetti@example.com",
    "status": "qualified",
    "company": "Ridgeline Property Group",
    "tags": ["past-customer"],
}

_CAMPAIGN = {
    "id": "3f1b6a2c-1d4e-4a7b-9c88-2f0f5a6b7c10",
    "name": "Spring Gutter Cleaning",
    "status": "draft",
    "type": "sms",
    "initial_message": "Hi {first_name}, ready to book your spring gutter cleaning?",
    "contact_count": 214,
}

_AUTOMATION = {
    "id": "7c9a1e55-2b3d-4f61-8a0c-90d1e2f3a4b5",
    "name": "New lead follow-up",
    "trigger_type": "contact_created",
    "trigger_config": {},
    "actions": [{"type": "wait", "config": {"hours": 2}}],
    "is_active": True,
}

_AGENT = {
    "id": "b21d7f40-9c33-4e6a-8f21-6d5c4b3a2019",
    "name": "Front Desk Receptionist",
    "channel_mode": "both",
    "is_active": True,
    "system_prompt": "You answer inbound calls for a home-service business.",
}

_CONVERSATION = {
    "id": "d0c9b8a7-6543-4210-9fed-cba987654321",
    "contact_id": 512,
    "contact_phone": "+15554829910",
    "last_message": "Sounds good, what time works?",
    "last_message_at": "2026-07-28T15:04:00+00:00",
    "unread_count": 1,
}


def _listing(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Shape a list result the way the post-Phase-1 list tools do."""

    return {
        "success": True,
        "data": items,
        "returned": len(items),
        "total": len(items),
        "has_more": False,
        "count": len(items),
    }


_LIST_RESULTS: dict[str, dict[str, Any]] = {
    "search_contacts": _listing([_CONTACT]),
    "find_contacts": _listing([_CONTACT]),
    "list_campaigns": _listing([_CAMPAIGN]),
    "list_campaign_contacts": _listing([_CONTACT]),
    "list_automations": _listing([_AUTOMATION]),
    "list_agents": _listing([_AGENT]),
    "list_recent_conversations": _listing([_CONVERSATION]),
    "list_appointments": _listing(
        [
            {
                "id": 88,
                "contact_id": 512,
                "scheduled_at": "2026-07-30T14:00:00+00:00",
                "duration_minutes": 60,
                "status": "scheduled",
            }
        ]
    ),
    "list_opportunities": _listing(
        [{"id": "op-1", "name": "Gutter package", "status": "open", "amount": 1250.0}]
    ),
    "list_offers": _listing([{"id": "of-1", "name": "20% off first clean", "is_active": False}]),
}

_SINGLE_RESULTS: dict[str, dict[str, Any]] = {
    "get_contact": {"success": True, "data": _CONTACT},
    "create_contact": {"success": True, "data": _CONTACT},
    "update_contact": {"success": True, "data": _CONTACT},
    "add_contact_note": {"success": True, "data": _CONTACT},
    "add_contact_tags": {"success": True, "data": {**_CONTACT, "tags": ["hot-lead"]}},
    "get_conversation": {
        "success": True,
        "conversation": _CONVERSATION,
        "data": [
            {
                "direction": "outbound",
                "body": "Following up on your gutter quote.",
                "created_at": "2026-07-27T18:00:00+00:00",
            }
        ],
        "returned": 1,
        "total": 1,
        "has_more": False,
    },
    "get_automation": {"success": True, "data": _AUTOMATION},
    "create_automation": {"success": True, "data": _AUTOMATION},
    "update_automation": {"success": True, "data": _AUTOMATION},
    "delete_automation": {"success": True, "message": "Automation deleted"},
    "enable_automation": {"success": True, "data": {**_AUTOMATION, "is_active": True}},
    "disable_automation": {"success": True, "data": {**_AUTOMATION, "is_active": False}},
    "get_agent": {"success": True, "data": _AGENT},
    "create_agent": {"success": True, "data": _AGENT},
    "update_agent": {"success": True, "data": _AGENT},
    "create_campaign": {"success": True, "data": _CAMPAIGN},
    "update_campaign": {"success": True, "data": _CAMPAIGN},
    "start_campaign": {"success": True, "message": "Campaign started"},
    "pause_campaign": {"success": True, "message": "Campaign paused"},
    "resume_campaign": {"success": True, "message": "Campaign resumed"},
    "summarize_campaign": {
        "success": True,
        "data": {
            "name": _CAMPAIGN["name"],
            "status": "completed",
            "sent": 214,
            "replies": 31,
            "appointments": 9,
        },
    },
    "get_offer_details": {"success": True, "data": {"id": "of-1", "name": "20% off"}},
    "create_offer_draft": {"success": True, "data": {"id": "of-2", "name": "New draft"}},
    "update_offer_draft": {"success": True, "data": {"id": "of-1", "name": "20% off"}},
    "get_dashboard_stats": {
        "success": True,
        "data": {
            "contacts": 1842,
            "campaigns": 6,
            "conversations": 311,
            "upcoming_appointments": 4,
        },
    },
    "get_today_queue": {
        "success": True,
        "data": {
            "generated_at": "2026-07-29T12:00:00+00:00",
            "items": [
                {"kind": "pending_approval", "title": "1 SMS awaiting approval"},
                {"kind": "draft_campaign", "title": "Spring Gutter Cleaning ready to launch"},
            ],
        },
    },
    "assign_ai_responder": {"success": True, "message": "Assigned AI responder"},
    "send_sms": {"success": True, "message": "SMS sent"},
    "plan_outbound_growth_workflow": {
        "success": True,
        "data": {"campaign_id": _CAMPAIGN["id"], "next_step": "review_draft"},
    },
    "search_help": {
        "success": True,
        "data": [
            {
                "title": "Creating an automation",
                "excerpt": "Open Automations, choose a trigger, then add actions in order.",
            }
        ],
        "returned": 1,
        "total": 1,
        "has_more": False,
    },
}


def stub_tool_result(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Return a plausible canned result for a tool call made during an eval."""

    if name in _LIST_RESULTS:
        return _LIST_RESULTS[name]
    if name in _SINGLE_RESULTS:
        return _SINGLE_RESULTS[name]
    return {"success": True, "data": {"tool": name, "arguments": arguments}}
