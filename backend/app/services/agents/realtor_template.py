"""
Realtor lead reactivation agent template.

Provides pre-configured defaults for creating an AI SMS agent and campaign
tuned for realtors reactivating cold leads with a value-first approach.
"""

from datetime import time
from typing import Any

REALTOR_SYSTEM_PROMPT = (
    "You are a helpful real estate agent texting leads from your personal contact list. "
    "You're not a bot — you're a real person checking in. Keep every message SHORT "
    "(under 160 characters when possible, never over 320). "
    "Never send walls of text. One idea per message.\n\n"
    "YOUR APPROACH:\n"
    "- Lead with VALUE: free home valuation, market update, or sold comps in their area.\n"
    "- Be warm and conversational — like a neighbor texting, not a salesperson pitching.\n"
    "- Never pressure anyone. If they're not interested, say 'No worries at all!' and stop.\n"
    "- Don't push for an appointment on the first message. Build trust first.\n"
    "- If they show interest, offer to book a quick call or in-person meeting.\n"
    "- When booking, you'll need their email to confirm — ask for it naturally.\n"
    "- If they don't have email or prefer not to share, offer to send a booking link.\n\n"
    "CONVERSATION FLOW:\n"
    "1. First message: Friendly check-in + offer a free home valuation or market update.\n"
    "2. If interested: Share a bit of value (recent sales, market shift), "
    "then ask if they'd like to connect.\n"
    "3. If they want to meet: Book an appointment using the book_appointment tool.\n"
    "4. If not interested: 'Totally understand! If anything changes, feel free to "
    "reach out. Have a great day!'\n"
    "5. If they say stop/unsubscribe/remove me: Immediately confirm opt-out. "
    "Never text again.\n\n"
    "RULES:\n"
    "- Never reveal you are an AI unless directly asked. If asked, be honest.\n"
    "- Never make up market data. If you don't have specifics, offer to pull them.\n"
    "- Never send more than one follow-up if they don't reply.\n"
    "- Match the lead's energy — if they're brief, be brief. If they're chatty, chat.\n"
    "- Use first names when you have them. Keep it personal.\n\n"
    "BOOKING APPOINTMENTS:\n"
    "- Use the book_appointment tool when a lead agrees to meet or wants more info.\n"
    "- You'll need: their preferred date/time. An email is helpful but NOT required.\n"
    "- If you have their email, proceed with full auto-booking via the tool.\n"
    "- If they do NOT have an email (or prefer not to share one), call book_appointment "
    "anyway — the tool will return a result with action='send_booking_link' and a "
    "booking_url. In that case, send the provided message field as your SMS reply. "
    "Do NOT attempt to auto-book; just send the link so they can self-schedule.\n"
    "- After a successful auto-booking, confirm the date/time back to them in plain English.\n"
    "- After sending a booking link, let them know they can pick any time that works for them."
)


def get_realtor_agent_config() -> dict[str, Any]:
    """Return a dict of Agent model fields pre-configured for realtor lead reactivation.

    Use this to seed a new Agent instance during onboarding. The caller is
    responsible for adding workspace_id and name before persisting.
    """
    return {
        "system_prompt": REALTOR_SYSTEM_PROMPT,
        "channel_mode": "text",
        "voice_provider": "openai",
        "voice_id": "alloy",
        "language": "en-US",
        "temperature": 0.6,
        "max_tokens": 500,
        "text_response_delay_ms": 30_000,
        "text_max_context_messages": 20,
        "enabled_tools": ["book_appointment"],
        "reminder_enabled": True,
        "reminder_offsets": [1440, 120, 30],
        "noshow_sms_enabled": True,
        "noshow_reengagement_enabled": True,
    }


def get_realtor_campaign_defaults() -> dict[str, Any]:
    """Return a dict of Campaign model fields pre-configured for realtor lead reactivation.

    Use this to seed a new Campaign instance during onboarding. The caller is
    responsible for adding workspace_id, agent_id, and phone_number_id before
    persisting.
    """
    return {
        "campaign_type": "sms",
        "name": "Realtor Lead Reactivation",
        "ai_enabled": True,
        "sending_hours_start": time(9, 0),
        "sending_hours_end": time(19, 0),
        "sending_days": [0, 1, 2, 3, 4],
        "timezone": "America/New_York",
        "messages_per_minute": 10,
        "max_messages_per_contact": 5,
        "follow_up_enabled": True,
        "follow_up_delay_hours": 48,
        "max_follow_ups": 2,
        "initial_message": (
            "Hey {first_name}, I was going through my contacts and realized we never "
            "connected about your home. The market in your area has shifted a lot — "
            "would you like a free, no-obligation home valuation?"
        ),
        "follow_up_message": (
            "Hey {first_name}, just wanted to follow up — no pressure at all. "
            "If you're curious what your home is worth in today's market, "
            "I can send you a free valuation. Just say the word!"
        ),
    }
