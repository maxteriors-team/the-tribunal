"""Default drip sequence configurations for home-service lead reactivation.

Each step defines:
- step: Ordinal position (0-indexed)
- delay_days: Days to wait after the previous step before sending
- message: Template with {first_name} placeholder
- type: Step classification for analytics
"""

from datetime import time
from typing import Any

# ---------------------------------------------------------------------------
# Value-first home-service reactivation sequence (6 steps over ~60 days)
#
# Strategy: Lead with a seasonal reminder / free value, rebuild trust with a
# past customer, then soft-ask to get them back on the schedule. If no response
# after 6 touches, send a friendly breakup message.
# ---------------------------------------------------------------------------

REACTIVATION_STEPS: list[dict[str, Any]] = [
    {
        "step": 0,
        "delay_days": 0,
        "message": (
            "Hey {first_name}, it's been a while! We're booking up for the "
            "season and wanted to check in — want a free quote to get your "
            "place looking its best again?"
        ),
        "type": "value_offer",
    },
    {
        "step": 1,
        "delay_days": 2,
        "message": (
            "Hey {first_name}, just following up — happy to put together a "
            "quick free quote whenever you're ready. No pressure at all!"
        ),
        "type": "gentle_follow_up",
    },
    {
        "step": 2,
        "delay_days": 5,
        "message": (
            "Hi {first_name}, quick heads up — our schedule is filling fast "
            "this season. If you'd like to get on the calendar, I can lock in "
            "a spot for you. Just say the word!"
        ),
        "type": "value_drop",
    },
    {
        "step": 3,
        "delay_days": 7,
        "message": (
            "Hey {first_name}, we just wrapped up a few homes in your "
            "neighborhood and they turned out great. Happy to do the same for "
            "you — want me to send over a quote?"
        ),
        "type": "social_proof",
    },
    {
        "step": 4,
        "delay_days": 16,
        "message": (
            "Hi {first_name}, I know it's been a bit — just wanted to check "
            "in. If you ever want to get back on our schedule, even just for a "
            "quote, I'm here. Want to set something up?"
        ),
        "type": "soft_appointment_ask",
    },
    {
        "step": 5,
        "delay_days": 30,
        "message": (
            "Hey {first_name}, I don't want to be that person who keeps "
            "texting! This'll be my last reach-out for now. Whenever you need "
            "us again, just text back. Thanks for being a customer!"
        ),
        "type": "breakup",
    },
]


def get_reactivation_drip_config() -> dict[str, Any]:
    """Return a dict of DripCampaign fields for home-service lead reactivation.

    The caller is responsible for adding workspace_id, agent_id, and
    from_phone_number before persisting.
    """
    return {
        "name": "Dead Lead Reactivation",
        "description": (
            "Automated 6-step value-first sequence to re-engage dormant customers. "
            "Leads with a seasonal offer, rebuilds trust, then soft-asks to book."
        ),
        "sequence_steps": REACTIVATION_STEPS,
        "sending_hours_start": time(9, 0),
        "sending_hours_end": time(19, 0),
        "sending_days": [0, 1, 2, 3, 4],  # Mon-Fri
        "timezone": "America/New_York",
        "messages_per_minute": 10,
    }
