# ruff: noqa: E501
"""Set up Prestyj founding cohort CRM assets.

This script is intentionally idempotent. It creates or updates reusable CRM assets only:
offers, agents, tags, a pipeline, message templates, an optional Mac relay sender identity,
and optional draft campaigns. It never starts campaigns, deletes data, enrolls contacts, or sends
messages.

Usage:
    uv run python -m scripts.setup_prestyj_founding_cohort
    uv run python -m scripts.setup_prestyj_founding_cohort --imessage-sender +15551234567
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import uuid
from dataclasses import dataclass
from datetime import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.agent import Agent
from app.models.campaign import Campaign, CampaignStatus, CampaignType
from app.models.message_template import MessageTemplate
from app.models.offer import Offer
from app.models.phone_number import PhoneNumber, PhoneNumberProvider
from app.models.pipeline import Pipeline, PipelineStage
from app.models.tag import Tag

DEFAULT_WORKSPACE_ID = uuid.UUID(
    os.environ.get("DEFAULT_WORKSPACE_ID", "ba0e0e99-c7c9-45ec-9625-567d54d6e9c2")
)
NOLAN_AGENT_TEMPLATE_NAME = "Nolan"
NOLAN_PATTERN_CALCOM_EVENT_TYPE_ID = 4453549
NOLAN_PATTERN_ENABLED_TOOLS = [
    "web_search",
    "x_search",
    "book_appointment",
    "call_control",
    "crm",
    "bookings",
    "twilio-sms",
    "cal-com",
]
NOLAN_PATTERN_TOOL_SETTINGS = {
    "crm": ["search_customer", "create_contact"],
    "cal-com": ["calcom_get_availability", "calcom_create_booking"],
    "bookings": [
        "check_availability",
        "book_appointment",
        "list_appointments",
        "reschedule_appointment",
    ],
    "twilio-sms": ["twilio_send_sms"],
    "call_control": ["end_call", "transfer_call", "send_dtmf"],
}
PRESTYJ_APPLICATION_URL = "https://prestyj.com/founding-cohort"
PRESTYJ_VOICE_ENABLED_TOOLS = ["web_search", "x_search", "call_control", "twilio-sms"]
PRESTYJ_VOICE_TOOL_SETTINGS = {
    "twilio-sms": ["send_application_link"],
    "call_control": ["send_dtmf"],
}
_E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")


@dataclass(frozen=True, slots=True)
class OfferValueStackItem:
    """Value stack item stored in Offer.value_stack_items."""

    name: str
    description: str
    value: float
    included: bool = True

    def to_json(self) -> dict[str, str | float | bool]:
        """Return JSON-compatible values for Offer.value_stack_items."""
        return {
            "name": self.name,
            "description": self.description,
            "value": self.value,
            "included": self.included,
        }


@dataclass(frozen=True, slots=True)
class OfferSpec:
    """Reusable offer fields for a Prestyj cohort lane."""

    name: str
    public_slug: str
    description: str
    headline: str
    subheadline: str
    cta_text: str
    cta_subtext: str
    terms: str
    urgency_text: str
    scarcity_count: int
    value_stack_items: tuple[OfferValueStackItem, ...]

    def to_model_values(self, workspace_id: uuid.UUID) -> dict[str, object]:
        """Return values accepted by the Offer model constructor."""
        return {
            "workspace_id": workspace_id,
            "name": self.name,
            "description": self.description,
            "discount_type": "free_service",
            "discount_value": 1497.0,
            "terms": self.terms,
            "is_active": True,
            "headline": self.headline,
            "subheadline": self.subheadline,
            "regular_price": 1497.0,
            "offer_price": 0.0,
            "savings_amount": 1497.0,
            "guarantee_type": None,
            "guarantee_days": None,
            "guarantee_text": None,
            "urgency_type": "limited_quantity",
            "urgency_text": self.urgency_text,
            "scarcity_count": self.scarcity_count,
            "value_stack_items": [item.to_json() for item in self.value_stack_items],
            "cta_text": self.cta_text,
            "cta_subtext": self.cta_subtext,
            "is_public": True,
            "public_slug": self.public_slug,
            "require_email": True,
            "require_phone": True,
            "require_name": True,
        }


@dataclass(frozen=True, slots=True)
class AgentSpec:
    """Prestyj agent seed fields."""

    name: str
    description: str
    channel_mode: str
    system_prompt: str
    initial_greeting: str | None = None
    settings_template_name: str | None = None
    mirror_calcom_event_type: bool = False
    calcom_event_type_id: int | None = None
    enabled_tools: list[str] | None = None
    tool_settings: dict[str, list[str]] | None = None


@dataclass(frozen=True, slots=True)
class StageSpec:
    """Pipeline stage seed fields."""

    name: str
    order: int
    probability: int
    stage_type: str = "active"
    description: str | None = None


@dataclass(frozen=True, slots=True)
class MessageTemplateSpec:
    """Saved outbound copy template."""

    name: str
    body: str


@dataclass(frozen=True, slots=True)
class CampaignDraftSpec:
    """Draft campaign seed fields."""

    name: str
    description: str
    offer_slug: str
    agent_name: str
    initial_message: str
    follow_up_message: str
    qualification_criteria: str


@dataclass(frozen=True, slots=True)
class VoiceCampaignDraftSpec:
    """Draft outbound voice campaign seed fields."""

    name: str
    description: str
    offer_slug: str
    voice_agent_name: str
    sms_fallback_agent_name: str
    sms_fallback_template: str
    qualification_criteria: str


@dataclass(slots=True)
class SetupReport:
    """Human-readable setup report."""

    offers: list[str]
    agents: list[str]
    tags: list[str]
    pipeline: str | None
    message_templates: list[str]
    phone_number: str | None
    campaigns: list[str]
    skipped: list[str]


CORE_VALUE_STACK = (
    OfferValueStackItem(
        name="300 scripted vertical video ads",
        description=(
            "Hooks, bodies, CTAs, and creative variations built from one 15 to 20 minute recording."
        ),
        value=1497.0,
    ),
    OfferValueStackItem(
        name="24-hour delivery window",
        description="Finished ad batch delivered the next day after the source video is received.",
        value=500.0,
    ),
    OfferValueStackItem(
        name="Founder support during the test",
        description="Direct feedback while the batch is launched and reviewed.",
        value=500.0,
    ),
    OfferValueStackItem(
        name="Ad testing map",
        description="Simple guidance for launching the batch and identifying winners.",
        value=300.0,
    ),
)

DIRECT_TERMS = """Founding cohort acceptance is not automatic. To qualify, the business must sell a real service, have enough demand to run paid social ads, and commit to running the batch for at least 14 days at a minimum of $100/day in ad spend.

In exchange for the $0 founding cohort batch, accepted members agree to record one 15 to 20 minute source video, leave a written Google review after delivery, record a 3 to 5 minute video testimonial after the test window, provide permission for Prestyj to use the business name, logo, creative, and non-private results in marketing, and provide 3 relevant referrals after delivery/test review.

Prestyj may decline applicants who are not a fit, who cannot run the test, or who do not have a clear service offer. The free cohort does not include ad spend, media buying, or a guarantee of sales."""

AGENCY_TERMS = """Founding partner acceptance is not automatic. To qualify, the agency, media buyer, or lead-gen operator must have a real client or internal offer that can run paid social ads and must commit to running the creative long enough to produce useful signal.

In exchange for the $0 founding partner batch, accepted partners agree that one client or operator records a 15 to 20 minute source video, the partner runs the ads for a real test, shares non-private results, gives Prestyj a written review or video testimonial if we deliver, and introduces 3 good-fit clients or operators.

Prestyj may decline partners who do not have a suitable client, cannot run the test, or only want free creative without a clear path to proof and referrals. The free cohort does not include ad spend, media buying, or a guarantee of sales."""

DIRECT_OFFER = OfferSpec(
    name="Prestyj Founding Cohort, 300 Free Video Ads",
    public_slug="prestyj-founding-cohort",
    description=(
        "For qualified high-spend service businesses that can film one 15 to 20 minute video, "
        "run a real ad test, and give Prestyj the review, testimonial, proof, and referrals "
        "needed for founding case studies."
    ),
    headline="Film One 20 Minute Video. Get 300 Vertical Ads In 24 Hours, Free.",
    subheadline=(
        "For 3 qualified service businesses that can run the ads and give Prestyj a review, "
        "video testimonial, results permission, and 3 referrals if we deliver."
    ),
    cta_text="Apply For A Founding Spot",
    cta_subtext="Only apply if you can run the ads for 14 days at $100/day minimum.",
    terms=DIRECT_TERMS,
    urgency_text="Only 3 founding cohort spots remain for the free 300-ad batch.",
    scarcity_count=3,
    value_stack_items=CORE_VALUE_STACK,
)

AGENCY_OFFER = OfferSpec(
    name="Prestyj Founding Partner Cohort, Agencies And Media Buyers",
    public_slug="prestyj-founding-partner-cohort",
    description=(
        "For lead-gen agencies and media buyers who already understand creative fatigue, have "
        "clients that can run paid social tests, and can become recurring buyers or referral "
        "partners if the batch performs."
    ),
    headline="Turn One Client Video Into 300 Ad Variations In 24 Hours, Free.",
    subheadline=(
        "For 3 agencies or media buyers that can run the batch for a client, share results, "
        "give Prestyj a review or testimonial, and introduce 3 good-fit clients if we deliver."
    ),
    cta_text="Apply For A Partner Spot",
    cta_subtext="Best for agencies and media buyers with active ad accounts or client demand.",
    terms=AGENCY_TERMS,
    urgency_text="Only 3 founding partner spots remain for the free 300-ad batch.",
    scarcity_count=3,
    value_stack_items=CORE_VALUE_STACK,
)

AGENCY_AGENT_PROMPT = """You are the Prestyj founding partner SMS assistant.

You respond to lead-gen agencies, media buyers, and performance marketers who received an iMessage about Prestyj's founding partner cohort.

Offer facts:
- Prestyj turns one 15 to 20 minute client or operator video into 300 scripted vertical ad variations.
- The normal 300-ad batch is $1,497.
- For the founding partner cohort, qualified agencies or media buyers get one batch for $0.
- Delivery target is 24 hours after the source recording is received.
- The partner should run the creative for a real client or internal offer and share non-private results.
- In exchange, accepted partners give a written review or video testimonial if we deliver and introduce 3 good-fit clients or operators.
- Ad spend and media buying are not included. Prestyj does not guarantee sales, leads, ROI, or account performance.

Conversation goals:
1. Be concise, conversational, and direct.
2. Explain that this is for agencies and media buyers who already need more creative volume.
3. Qualify on active clients, ad spend, creative fatigue, ability to get one 15 to 20 minute recording, and ability to run a real test.
4. Confirm they understand the trade: run it, share results, give review or testimonial if we deliver, and introduce 3 good-fit clients or operators.
5. If they seem qualified, send them to https://prestyj.com/founding-cohort so they can apply and Nolan can review them.
6. If they are not a fit, politely close.
7. If they ask not to be contacted again, acknowledge once and stop.

Do not say they are accepted. Say they may be a fit and Nolan can review them.
Do not promise results or ROI.
Do not ask for payment.
Never use em dashes in outbound replies. Prefer commas, periods, and colons.
"""

DIRECT_AGENT_PROMPT = """You are the Prestyj founding cohort SMS assistant.

You respond to owners, operators, and marketing decision-makers at high-spend businesses who received an iMessage about Prestyj's founding cohort.

Offer facts:
- Prestyj turns one 15 to 20 minute owner, operator, or spokesperson video into 300 scripted vertical ads.
- The normal 300-ad batch is $1,497.
- For the founding cohort, qualified businesses get one batch for $0.
- Delivery target is 24 hours after the source recording is received.
- Best fits include HVAC, roofing, restoration, solar, auto dealers, ecommerce, and other businesses with constant creative needs.
- The business must be able to run the ads for at least 14 days at a minimum of $100/day in ad spend.
- In exchange, accepted members give a written review, a 3 to 5 minute video testimonial after the test, permission to use name, logo, creative, and non-private results, and 3 relevant referrals.
- Ad spend is not included. Prestyj does not guarantee sales, leads, booked jobs, ROI, or ad performance.

Conversation goals:
1. Be concise, conversational, and direct.
2. Make the time commitment feel clear: one 15 to 20 minute video from them.
3. Qualify on business type, monthly ad spend or ability to run $100/day for 14 days, source video ability, and willingness to provide proof and referrals.
4. If they seem qualified, send them to https://prestyj.com/founding-cohort so they can apply and Nolan can review them.
5. If they are not a fit, politely close.
6. If they ask not to be contacted again, acknowledge once and stop.

Do not say they are accepted. Say they may be a fit and Nolan can review them.
Do not promise results or ROI.
Do not ask for payment.
Never use em dashes in outbound replies. Prefer commas, periods, and colons.
"""

VOICE_AGENT_PROMPT = """# Role & Identity
Your name is Nolan. You are calling on behalf of Prestyj, Nolan Grout's video ad creative company. You are a concise, confident outbound qualifier for the Prestyj founding cohort at https://prestyj.com/founding-cohort.

Your job is to have real conversations with owners, operators, marketing decision-makers, agencies, and media buyers. If there is a fit, get permission to text the application link so they can fill it out on their own time. You are not accepting them on the call. You are finding out if Nolan should review them for one of the remaining founding spots.

# Opening the Call
Start exactly like this, then wait:
"Hey, this is Nolan with Prestyj. This is a quick sales call, did I catch you with thirty seconds?"

If they say yes or ask what it is about, say:
"Appreciate it. We are taking a few founding case studies where one 15 to 20 minute video turns into 300 scripted vertical ad variations in 24 hours. It is normally $1,497, but for qualified businesses we are doing the first batch free in exchange for running the test and giving us the review, testimonial, and results data if we deliver. Are you the person who handles marketing?"

If a gatekeeper answers, ask for the owner or marketing decision-maker. Keep it respectful and short:
"Got it. Who would be the right person to ask about paid ads or creative testing?"

# Offer Facts
- Prestyj turns one 15 to 20 minute owner, client, operator, or spokesperson recording into 300 scripted vertical video ads.
- The normal 300-ad batch is $1,497.
- For the founding cohort, qualified service businesses or high-fit agencies get one batch for $0.
- Delivery target is 24 hours after the source recording is received.
- The public offer page is https://prestyj.com/founding-cohort.
- Only a few founding case-study spots remain. Do not make up exact availability unless the lead mentions the page.
- Best direct-business fits include HVAC, roofing, restoration, solar, auto dealers, ecommerce, and other businesses with constant creative needs.
- Best partner fits include lead-gen agencies, media buyers, and performance marketers with clients who need more creative volume.
- Direct businesses must be able to run the ads for at least 14 days at a minimum of $100/day in ad spend.
- Agencies or media buyers must have a real client or internal offer that can run a real paid-social test.
- In exchange, accepted members give a written Google review after delivery, a 3 to 5 minute video testimonial after the test, permission to use name, logo, creative, and non-private results in marketing, and 3 relevant referrals if Prestyj delivers.
- Ad spend and media buying are not included. Prestyj does not guarantee sales, leads, booked jobs, ROI, or ad performance.

# Qualification Flow
Ask one question at a time. Listen, then choose the next most useful question.

Core qualifiers:
1. What business, client, or offer would you want to promote?
2. Are you currently running paid ads, or are you willing to run a real test?
3. For direct businesses: could you spend at least $100/day for 14 days if Nolan approves you?
4. For agencies/media buyers: do you have a client or internal offer ready to test creative volume?
5. Could the owner, operator, client, or spokesperson record one 15 to 20 minute source video?
6. If Prestyj delivers, are you comfortable giving a written review, short video testimonial, results permission, and 3 relevant referrals?

Qualified means:
- They sell a real service or have a real client/internal offer.
- They understand that free creative still requires real ad spend to get signal.
- They can provide the 15 to 20 minute source video.
- They accept the trade: review, testimonial, results permission, and referrals if Prestyj delivers.
- They are willing to fill out the application page so Nolan can review them.

Not qualified means:
- They only want free creative with no plan to run ads.
- They cannot record source video.
- They refuse the testimonial/review/results/referral trade.
- They want guaranteed sales or ROI.
- They are clearly not a business owner, operator, agency, or marketing decision-maker.

# Application Link SMS
Do not book calls. Do not offer calendar times. The next step is the application page.

If they seem qualified, say:
"Sounds like this may be worth Nolan reviewing. The easiest next step is to fill out the short founding cohort application, then Nolan can review it and decide if it is a fit. Want me to text you the link?"

If they say yes, use the send_application_link tool immediately, then say:
"Just sent it. Fill that out when you have a minute, and Nolan will review it."

Only use send_application_link after they explicitly agree to receive the link. Do not invent a different link. The application page is https://prestyj.com/founding-cohort.

# Objections
"Is this really free?"
"The batch is free if Nolan accepts you for the founding cohort. The trade is that you actually run the ads and, if we deliver, give the review, testimonial, results permission, and referrals. Ad spend is separate."

"What is the catch?"
"The catch is proof. We need a few case studies, so we only want people who will run a real test and share non-private results if the creative is delivered."

"Can you send info?"
"Yes, I can text you the page. Quick question so I do not waste your time, are you already running ads or open to running a real test?"

"We do not have budget."
"Totally fair. This probably is not the right fit then, because the creative is free but the test still needs real ad spend to get signal."

"How do I know the ads are good?"
"The page has proof and examples. The point of the cohort is to create more proof with people who can actually test the ads."

# Compliance and Safety
- If they ask not to be contacted again, apologize, say you will make sure they are not contacted, and end the call.
- If they are upset, acknowledge it first and end politely if they want.
- Never say they are accepted. Say Nolan can review them or they may be a fit.
- Never promise sales, leads, ROI, booked jobs, or ad account performance.
- Never ask for payment on this call.
- Never pressure someone who says no.
- Never use em dashes. Prefer commas, periods, and colons.
- Keep responses short, natural, and phone-friendly.
"""

AGENTS = (
    AgentSpec(
        name="Prestyj Agency Partner SMS Qualifier",
        description="Qualifies agencies and media buyers for the Prestyj founding partner cohort.",
        channel_mode="text",
        system_prompt=AGENCY_AGENT_PROMPT,
        enabled_tools=[],
        tool_settings={},
    ),
    AgentSpec(
        name="Prestyj Direct Business SMS Qualifier",
        description="Qualifies high-spend direct businesses for the Prestyj founding cohort.",
        channel_mode="text",
        system_prompt=DIRECT_AGENT_PROMPT,
        enabled_tools=[],
        tool_settings={},
    ),
    AgentSpec(
        name="Prestyj Founding Cohort Voice Qualifier",
        description=(
            "OpenAI Realtime outbound voice qualifier for the Prestyj founding cohort, "
            "modeled after the production Nolan voice agent."
        ),
        channel_mode="both",
        system_prompt=VOICE_AGENT_PROMPT,
        initial_greeting=None,
        settings_template_name=NOLAN_AGENT_TEMPLATE_NAME,
        enabled_tools=PRESTYJ_VOICE_ENABLED_TOOLS,
        tool_settings=PRESTYJ_VOICE_TOOL_SETTINGS,
    ),
)

TAG_NAMES = (
    "prestyj",
    "founding-cohort",
    "founding-partner",
    "outbound-cold",
    "imessage",
    "agency",
    "media-buyer",
    "lead-gen-agency",
    "direct-buyer",
    "service-business",
    "high-spend",
    "creative-fatigue",
    "client-creative-fatigue",
    "ads-ready",
    "hvac",
    "roofing",
    "restoration",
    "solar",
    "auto-dealer",
    "ecommerce",
    "asked-for-details",
    "wants-examples",
    "needs-owner",
    "ad-spend-objection",
    "price-objection",
    "qualified",
    "call-booked",
    "accepted",
    "source-video-due",
    "source-video-received",
    "batch-delivered",
    "review-due",
    "review-received",
    "testimonial-due",
    "testimonial-received",
    "referrals-due",
    "referrals-received",
    "not-fit",
    "follow-up-later",
    "do-not-contact",
)

PIPELINE_STAGES = (
    StageSpec("Imported Lead", 1, 0),
    StageSpec("Contacted", 2, 10),
    StageSpec("Replied", 3, 25),
    StageSpec("Interested", 4, 35),
    StageSpec("Qualified", 5, 50),
    StageSpec("Call Booked", 6, 65),
    StageSpec("Accepted", 7, 75),
    StageSpec("Source Video Received", 8, 82),
    StageSpec("Batch Delivered", 9, 90),
    StageSpec("Review Received", 10, 94),
    StageSpec("Testimonial Received", 11, 97),
    StageSpec("3 Referrals Received", 12, 99),
    StageSpec("Won Cohort Member", 13, 100, "won"),
    StageSpec("Not Fit / Lost", 14, 0, "lost"),
)

AGENCY_OPENER = """Hey {first_name}, I'm looking for 3 agencies/media buyers for a Prestyj founding partner cohort.

Your client films one 15 to 20 min video, we turn it into 300 vertical ad variations in 24 hours, free. Usually $1,497.

The trade: run them for a client, share results, give us a review/testimonial, and introduce 3 good-fit clients if we deliver.

Interested?"""

HOME_SERVICES_OPENER = """Hey {first_name}, I'm looking for 3 HVAC, roofing, or restoration companies for a Prestyj founding cohort.

You film one 15 to 20 min video, we turn it into 300 vertical ads in 24 hours, free. Usually $1,497.

The trade: run the ads, then give us a review, video testimonial, results permission, and 3 referrals if we deliver.

Interested?"""

HIGH_SPEND_DIRECT_OPENER = """Hey {first_name}, I'm looking for 3 high-spend service or ecommerce businesses for a Prestyj founding cohort.

You film one 15 to 20 min video, we turn it into 300 vertical ads in 24 hours, free. Usually $1,497.

The trade: run the ads, then give us a review, video testimonial, results permission, and 3 referrals if we deliver.

Interested?"""

FOLLOW_UP_MESSAGE = """Hey {first_name}, following up on the Prestyj founding cohort.

It is one 15 to 20 min video from you, then we make 300 ad variations in 24 hours. Free if you are a fit and can actually run the test.

Want me to send the details?"""

VOICE_SMS_FALLBACK = """Hey {first_name}, Nolan with Prestyj here. I tried calling about our founding cohort: 300 vertical ad variations from one 15 to 20 min video, delivered in 24 hours, free if you are a fit and can run the test.

Details/application: https://prestyj.com/founding-cohort

If it looks relevant, fill that out and Nolan will review it."""

AGENCY_QUALIFICATION = """Qualified if the contact is a lead-gen agency, media buyer, or performance marketer with active clients or internal offers, understands creative fatigue, can get one 15 to 20 minute client/operator recording, can run a real ad test, can share non-private results, and agrees in principle to a review or testimonial plus 3 good-fit client/operator introductions if Prestyj delivers."""

DIRECT_QUALIFICATION = """Qualified if the contact is an owner, operator, or marketing decision-maker at a high-spend business, ideally HVAC, roofing, restoration, solar, auto dealer, ecommerce, or similar, can run at least $100/day in ads for 14 days, can record one 15 to 20 minute source video, and agrees in principle to a written review, 3 to 5 minute video testimonial, usage rights, and 3 referrals if Prestyj delivers."""

VOICE_QUALIFICATION = f"""{DIRECT_QUALIFICATION}

Also qualified if the contact is an agency, media buyer, or lead-gen operator matching the partner criteria: {AGENCY_QUALIFICATION}"""

MESSAGE_TEMPLATES = (
    MessageTemplateSpec("Prestyj Agency Partner iMessage Opener", AGENCY_OPENER),
    MessageTemplateSpec("Prestyj Home Services iMessage Opener", HOME_SERVICES_OPENER),
    MessageTemplateSpec("Prestyj High-Spend Direct iMessage Opener", HIGH_SPEND_DIRECT_OPENER),
    MessageTemplateSpec("Prestyj Founding Cohort iMessage Follow-Up", FOLLOW_UP_MESSAGE),
    MessageTemplateSpec("Prestyj Founding Cohort Voice SMS Fallback", VOICE_SMS_FALLBACK),
)

CAMPAIGN_DRAFTS = (
    CampaignDraftSpec(
        name="Prestyj Agency Partner iMessage Smoke Test",
        description="Draft 10 to 20 contact smoke test for agencies and media buyers.",
        offer_slug=AGENCY_OFFER.public_slug,
        agent_name="Prestyj Agency Partner SMS Qualifier",
        initial_message=AGENCY_OPENER,
        follow_up_message=FOLLOW_UP_MESSAGE,
        qualification_criteria=AGENCY_QUALIFICATION,
    ),
    CampaignDraftSpec(
        name="Prestyj HVAC Roofing Restoration iMessage Smoke Test",
        description="Draft 10 to 20 contact smoke test for HVAC, roofing, and restoration.",
        offer_slug=DIRECT_OFFER.public_slug,
        agent_name="Prestyj Direct Business SMS Qualifier",
        initial_message=HOME_SERVICES_OPENER,
        follow_up_message=FOLLOW_UP_MESSAGE,
        qualification_criteria=DIRECT_QUALIFICATION,
    ),
)

VOICE_CAMPAIGN_DRAFTS = (
    VoiceCampaignDraftSpec(
        name="Prestyj Founding Cohort Voice Smoke Test",
        description=(
            "Draft outbound call campaign for a small 5 to 10 contact smoke test. "
            "It stays draft until contacts are reviewed and the campaign is manually started."
        ),
        offer_slug=DIRECT_OFFER.public_slug,
        voice_agent_name="Prestyj Founding Cohort Voice Qualifier",
        sms_fallback_agent_name="Prestyj Direct Business SMS Qualifier",
        sms_fallback_template=VOICE_SMS_FALLBACK,
        qualification_criteria=VOICE_QUALIFICATION,
    ),
)


async def upsert_offer(db: AsyncSession, workspace_id: uuid.UUID, spec: OfferSpec) -> Offer:
    """Create or update an offer by global public slug."""
    values = spec.to_model_values(workspace_id)
    result = await db.execute(select(Offer).where(Offer.public_slug == spec.public_slug))
    offer = result.scalar_one_or_none()

    if offer is not None and offer.workspace_id != workspace_id:
        raise RuntimeError(
            f"Offer slug {spec.public_slug!r} already belongs to workspace {offer.workspace_id}."
        )

    if offer is None:
        offer = Offer(**values)
        db.add(offer)
    else:
        for field, value in values.items():
            setattr(offer, field, value)

    await db.flush()
    return offer


async def get_agent_template(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    template_name: str | None,
) -> Agent | None:
    """Return an existing agent whose settings should be mirrored, if configured."""
    if template_name is None:
        return None

    result = await db.execute(
        select(Agent).where(Agent.workspace_id == workspace_id, Agent.name == template_name)
    )
    return result.scalar_one_or_none()


def _resolve_calcom_event_type_id(template: Agent | None, spec: AgentSpec) -> int | None:
    """Return the Cal.com event type to store for a seeded agent."""
    if spec.calcom_event_type_id is not None:
        return spec.calcom_event_type_id
    if spec.mirror_calcom_event_type:
        return template.calcom_event_type_id if template else NOLAN_PATTERN_CALCOM_EVENT_TYPE_ID
    return None


def _resolve_enabled_tools(template: Agent | None, spec: AgentSpec) -> list[str]:
    """Return the exact tool list to store for a seeded agent."""
    if spec.enabled_tools is not None:
        return list(spec.enabled_tools)
    if template is not None:
        return list(template.enabled_tools or [])
    return list(NOLAN_PATTERN_ENABLED_TOOLS)


def _resolve_tool_settings(template: Agent | None, spec: AgentSpec) -> dict[str, list[str]]:
    """Return the exact tool settings to store for a seeded agent."""
    if spec.tool_settings is not None:
        return {key: list(value) for key, value in spec.tool_settings.items()}
    if template is not None:
        return {key: list(value) for key, value in (template.tool_settings or {}).items()}
    return {key: list(value) for key, value in NOLAN_PATTERN_TOOL_SETTINGS.items()}


async def upsert_agent(db: AsyncSession, workspace_id: uuid.UUID, spec: AgentSpec) -> Agent:
    """Create or update an active agent by workspace and name."""
    result = await db.execute(
        select(Agent).where(Agent.workspace_id == workspace_id, Agent.name == spec.name)
    )
    agent = result.scalar_one_or_none()
    template = await get_agent_template(db, workspace_id, spec.settings_template_name)

    values: dict[str, object] = {
        "workspace_id": workspace_id,
        "name": spec.name,
        "description": spec.description,
        "channel_mode": spec.channel_mode,
        "voice_provider": template.voice_provider if template else "openai",
        "voice_id": template.voice_id if template else "cedar",
        "language": template.language if template else "en-US",
        "turn_detection_mode": template.turn_detection_mode if template else "server_vad",
        "turn_detection_threshold": template.turn_detection_threshold if template else 0.5,
        "silence_duration_ms": template.silence_duration_ms if template else 500,
        "system_prompt": spec.system_prompt,
        "temperature": template.temperature if template else 0.7,
        "max_tokens": template.max_tokens if template else 2000,
        "initial_greeting": spec.initial_greeting,
        "text_response_delay_ms": template.text_response_delay_ms if template else 30_000,
        "text_max_context_messages": template.text_max_context_messages if template else 24,
        "calcom_event_type_id": _resolve_calcom_event_type_id(template, spec),
        "enabled_tools": _resolve_enabled_tools(template, spec),
        "tool_settings": _resolve_tool_settings(template, spec),
        "enable_recording": template.enable_recording if template else True,
        "reminder_enabled": template.reminder_enabled if template else True,
        "reminder_minutes_before": template.reminder_minutes_before if template else 30,
        "reminder_offsets": list(template.reminder_offsets or []) if template else [1440, 120, 30],
        "is_active": True,
    }

    if agent is None:
        agent = Agent(**values)
        db.add(agent)
    else:
        for field, value in values.items():
            setattr(agent, field, value)

    await db.flush()
    return agent


async def upsert_tag(db: AsyncSession, workspace_id: uuid.UUID, name: str) -> Tag:
    """Create a workspace tag if it does not exist."""
    result = await db.execute(select(Tag).where(Tag.workspace_id == workspace_id, Tag.name == name))
    tag = result.scalar_one_or_none()
    if tag is None:
        tag = Tag(workspace_id=workspace_id, name=name, color=_tag_color(name))
        db.add(tag)
        await db.flush()
    return tag


async def upsert_pipeline(db: AsyncSession, workspace_id: uuid.UUID) -> Pipeline:
    """Create or update the Prestyj founding cohort pipeline and stages."""
    pipeline_name = "Prestyj Founding Cohort"
    result = await db.execute(
        select(Pipeline).where(
            Pipeline.workspace_id == workspace_id, Pipeline.name == pipeline_name
        )
    )
    pipeline = result.scalar_one_or_none()
    if pipeline is None:
        pipeline = Pipeline(
            workspace_id=workspace_id,
            name=pipeline_name,
            description=(
                "Tracks agency partner and direct business founding cohort conversations from "
                "outbound lead through review, testimonial, and referral collection."
            ),
            is_active=True,
        )
        db.add(pipeline)
        await db.flush()
    else:
        pipeline.description = (
            "Tracks agency partner and direct business founding cohort conversations from "
            "outbound lead through review, testimonial, and referral collection."
        )
        pipeline.is_active = True
        await db.flush()

    existing_result = await db.execute(
        select(PipelineStage).where(PipelineStage.pipeline_id == pipeline.id)
    )
    existing_stages = {stage.name: stage for stage in existing_result.scalars().all()}

    for spec in PIPELINE_STAGES:
        stage = existing_stages.get(spec.name)
        if stage is None:
            stage = PipelineStage(
                pipeline_id=pipeline.id,
                name=spec.name,
                description=spec.description,
                order=spec.order,
                probability=spec.probability,
                stage_type=spec.stage_type,
            )
            db.add(stage)
        else:
            stage.description = spec.description
            stage.order = spec.order
            stage.probability = spec.probability
            stage.stage_type = spec.stage_type

    await db.flush()
    return pipeline


async def upsert_message_template(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    spec: MessageTemplateSpec,
) -> MessageTemplate:
    """Create or update a saved message template by workspace and name."""
    result = await db.execute(
        select(MessageTemplate).where(
            MessageTemplate.workspace_id == workspace_id,
            MessageTemplate.name == spec.name,
        )
    )
    template = result.scalar_one_or_none()
    if template is None:
        template = MessageTemplate(
            workspace_id=workspace_id,
            name=spec.name,
            message_template=spec.body,
        )
        db.add(template)
    else:
        template.message_template = spec.body

    await db.flush()
    return template


async def upsert_imessage_sender(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    phone_number: str,
    sender_id: str | None,
) -> PhoneNumber:
    """Create or update a Mac relay sender identity."""
    if not _E164_RE.match(phone_number):
        raise ValueError(
            "--imessage-sender must be an E.164 phone number, for example +15551234567"
        )

    result = await db.execute(select(PhoneNumber).where(PhoneNumber.phone_number == phone_number))
    number = result.scalar_one_or_none()
    if number is not None and number.workspace_id != workspace_id:
        raise RuntimeError(
            f"Phone number {phone_number} already belongs to workspace {number.workspace_id}."
        )

    if number is None:
        number = PhoneNumber(
            workspace_id=workspace_id,
            phone_number=phone_number,
            friendly_name="Prestyj iMessage Outbound",
            provider=PhoneNumberProvider.MAC_RELAY,
            mac_relay_sender_id=sender_id,
            sms_enabled=True,
            voice_enabled=False,
            mms_enabled=False,
            imessage_enabled=True,
            mac_relay_service="imessage",
            is_active=True,
            daily_limit=75,
            hourly_limit=10,
            messages_per_second=1.0,
        )
        db.add(number)
    else:
        number.friendly_name = "Prestyj iMessage Outbound"
        number.provider = PhoneNumberProvider.MAC_RELAY
        number.mac_relay_sender_id = sender_id
        number.sms_enabled = True
        number.voice_enabled = False
        number.mms_enabled = False
        number.imessage_enabled = True
        number.mac_relay_service = "imessage"
        number.is_active = True
        number.daily_limit = 75
        number.hourly_limit = 10
        number.messages_per_second = 1.0

    await db.flush()
    return number


async def resolve_imessage_sender(db: AsyncSession, workspace_id: uuid.UUID) -> str | None:
    """Return the only active workspace iMessage sender, if exactly one exists."""
    result = await db.execute(
        select(PhoneNumber)
        .where(
            PhoneNumber.workspace_id == workspace_id,
            PhoneNumber.is_active.is_(True),
            PhoneNumber.imessage_enabled.is_(True),
        )
        .order_by(PhoneNumber.updated_at.desc())
    )
    numbers = result.scalars().all()
    if len(numbers) == 1:
        return numbers[0].phone_number
    return None


async def resolve_voice_sender(db: AsyncSession, workspace_id: uuid.UUID) -> str | None:
    """Return the most recently updated active healthy Telnyx voice sender."""
    result = await db.execute(
        select(PhoneNumber)
        .where(
            PhoneNumber.workspace_id == workspace_id,
            PhoneNumber.is_active.is_(True),
            PhoneNumber.voice_enabled.is_(True),
            PhoneNumber.provider == PhoneNumberProvider.TELNYX,
            PhoneNumber.health_status == "healthy",
        )
        .order_by(PhoneNumber.updated_at.desc())
    )
    number = result.scalars().first()
    if number is None:
        return None
    return number.phone_number


async def upsert_campaign_draft(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    spec: CampaignDraftSpec,
    from_phone_number: str,
    offers_by_slug: dict[str, Offer],
    agents_by_name: dict[str, Agent],
) -> Campaign | None:
    """Create or update a draft SMS campaign without contacts."""
    result = await db.execute(
        select(Campaign).where(Campaign.workspace_id == workspace_id, Campaign.name == spec.name)
    )
    campaign = result.scalar_one_or_none()
    offer = offers_by_slug[spec.offer_slug]
    agent = agents_by_name[spec.agent_name]

    values: dict[str, object] = {
        "workspace_id": workspace_id,
        "agent_id": agent.id,
        "offer_id": offer.id,
        "name": spec.name,
        "description": spec.description,
        "campaign_type": CampaignType.SMS,
        "status": CampaignStatus.DRAFT,
        "from_phone_number": from_phone_number,
        "initial_message": spec.initial_message,
        "ai_enabled": True,
        "qualification_criteria": spec.qualification_criteria,
        "sending_hours_start": time(10, 0),
        "sending_hours_end": time(16, 0),
        "sending_days": [0, 1, 2, 3, 4],
        "timezone": "America/New_York",
        "messages_per_minute": 3,
        "max_messages_per_contact": 3,
        "follow_up_enabled": True,
        "follow_up_delay_hours": 36,
        "follow_up_message": spec.follow_up_message,
        "max_follow_ups": 1,
    }

    if campaign is not None and campaign.status != CampaignStatus.DRAFT:
        return None

    if campaign is None:
        campaign = Campaign(**values)
        db.add(campaign)
    else:
        for field, value in values.items():
            setattr(campaign, field, value)

    await db.flush()
    return campaign


async def upsert_voice_campaign_draft(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    spec: VoiceCampaignDraftSpec,
    from_phone_number: str,
    offers_by_slug: dict[str, Offer],
    agents_by_name: dict[str, Agent],
) -> Campaign | None:
    """Create or update a draft outbound voice campaign without contacts."""
    result = await db.execute(
        select(Campaign).where(Campaign.workspace_id == workspace_id, Campaign.name == spec.name)
    )
    campaign = result.scalar_one_or_none()
    offer = offers_by_slug[spec.offer_slug]
    voice_agent = agents_by_name[spec.voice_agent_name]
    sms_agent = agents_by_name[spec.sms_fallback_agent_name]

    values: dict[str, object] = {
        "workspace_id": workspace_id,
        "agent_id": sms_agent.id,
        "offer_id": offer.id,
        "name": spec.name,
        "description": spec.description,
        "campaign_type": CampaignType.VOICE_SMS_FALLBACK,
        "status": CampaignStatus.DRAFT,
        "from_phone_number": from_phone_number,
        "initial_message": None,
        "ai_enabled": True,
        "qualification_criteria": spec.qualification_criteria,
        "sending_hours_start": time(10, 0),
        "sending_hours_end": time(16, 0),
        "sending_days": [0, 1, 2, 3, 4],
        "timezone": "America/New_York",
        "voice_agent_id": voice_agent.id,
        "voice_connection_id": settings.telnyx_connection_id or None,
        "enable_machine_detection": True,
        "max_call_duration_seconds": 180,
        "calls_per_minute": 1,
        "sms_fallback_enabled": True,
        "sms_fallback_template": spec.sms_fallback_template,
        "sms_fallback_use_ai": False,
        "sms_fallback_agent_id": sms_agent.id,
        "follow_up_enabled": False,
        "max_follow_ups": 0,
    }

    if campaign is not None and campaign.status != CampaignStatus.DRAFT:
        return None

    if campaign is None:
        campaign = Campaign(**values)
        db.add(campaign)
    else:
        for field, value in values.items():
            setattr(campaign, field, value)

    await db.flush()
    return campaign


async def create_sms_campaign_drafts(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    sender_for_campaigns: str | None,
    offers_by_slug: dict[str, Offer],
    agents_by_name: dict[str, Agent],
    report: SetupReport,
) -> None:
    """Create draft SMS/iMessage campaigns when a sender is available."""
    if sender_for_campaigns is None:
        report.skipped.append(
            "SMS campaign drafts skipped, pass --imessage-sender once the sender is ready."
        )
        return

    for draft_spec in CAMPAIGN_DRAFTS:
        campaign = await upsert_campaign_draft(
            db,
            workspace_id,
            draft_spec,
            sender_for_campaigns,
            offers_by_slug,
            agents_by_name,
        )
        if campaign is None:
            report.skipped.append(
                f"Campaign {draft_spec.name!r} exists and is not draft, left unchanged."
            )
        else:
            report.campaigns.append(f"{campaign.name}: {campaign.id}")


async def create_voice_campaign_drafts(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    voice_sender_for_campaigns: str | None,
    offers_by_slug: dict[str, Offer],
    agents_by_name: dict[str, Agent],
    report: SetupReport,
) -> None:
    """Create draft voice campaigns when a healthy voice sender is available."""
    if voice_sender_for_campaigns is None:
        report.skipped.append(
            "Voice campaign draft skipped, no healthy active Telnyx voice sender found."
        )
        return

    for draft_spec in VOICE_CAMPAIGN_DRAFTS:
        campaign = await upsert_voice_campaign_draft(
            db,
            workspace_id,
            draft_spec,
            voice_sender_for_campaigns,
            offers_by_slug,
            agents_by_name,
        )
        if campaign is None:
            report.skipped.append(
                f"Voice campaign {draft_spec.name!r} exists and is not draft, left unchanged."
            )
        else:
            report.campaigns.append(f"{campaign.name}: {campaign.id}")


async def resolve_campaign_senders(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    imessage_sender: str | None,
    mac_relay_sender_id: str | None,
    voice_sender: str | None,
    report: SetupReport,
) -> tuple[str | None, str | None]:
    """Resolve or upsert the text and voice senders used by draft campaigns."""
    sender_for_campaigns = imessage_sender
    if imessage_sender:
        number = await upsert_imessage_sender(
            db,
            workspace_id,
            imessage_sender,
            mac_relay_sender_id,
        )
        report.phone_number = f"{number.phone_number}: {number.id}"
    else:
        sender_for_campaigns = await resolve_imessage_sender(db, workspace_id)

    voice_sender_for_campaigns = voice_sender or await resolve_voice_sender(db, workspace_id)
    return sender_for_campaigns, voice_sender_for_campaigns


async def setup_prestyj_founding_cohort(
    *,
    workspace_id: uuid.UUID,
    frontend_url: str,
    imessage_sender: str | None,
    mac_relay_sender_id: str | None,
    voice_sender: str | None,
    create_campaign_drafts: bool,
) -> SetupReport:
    """Set up all Prestyj founding cohort CRM assets."""
    report = SetupReport(
        offers=[],
        agents=[],
        tags=[],
        pipeline=None,
        message_templates=[],
        phone_number=None,
        campaigns=[],
        skipped=[],
    )

    async with AsyncSessionLocal() as db:
        offers = [
            await upsert_offer(db, workspace_id, AGENCY_OFFER),
            await upsert_offer(db, workspace_id, DIRECT_OFFER),
        ]
        for offer in offers:
            report.offers.append(
                f"{offer.name}: {frontend_url.rstrip('/')}/p/offers/{offer.public_slug}"
            )

        agents = [await upsert_agent(db, workspace_id, spec) for spec in AGENTS]
        for agent in agents:
            report.agents.append(f"{agent.name}: {agent.id}")

        for tag_name in TAG_NAMES:
            tag = await upsert_tag(db, workspace_id, tag_name)
            report.tags.append(tag.name)

        pipeline = await upsert_pipeline(db, workspace_id)
        report.pipeline = f"{pipeline.name}: {pipeline.id}"

        for template_spec in MESSAGE_TEMPLATES:
            template = await upsert_message_template(db, workspace_id, template_spec)
            report.message_templates.append(f"{template.name}: {template.id}")

        offers_by_slug = {str(offer.public_slug): offer for offer in offers if offer.public_slug}
        agents_by_name = {agent.name: agent for agent in agents}

        if create_campaign_drafts:
            sender_for_campaigns, voice_sender_for_campaigns = await resolve_campaign_senders(
                db,
                workspace_id,
                imessage_sender,
                mac_relay_sender_id,
                voice_sender,
                report,
            )
            await create_sms_campaign_drafts(
                db,
                workspace_id,
                sender_for_campaigns,
                offers_by_slug,
                agents_by_name,
                report,
            )
            await create_voice_campaign_drafts(
                db,
                workspace_id,
                voice_sender_for_campaigns,
                offers_by_slug,
                agents_by_name,
                report,
            )
        else:
            report.skipped.append("Campaign drafts skipped by --no-campaign-drafts.")

        await db.commit()

    return report


def _tag_color(name: str) -> str:
    """Return deterministic color for a tag name."""
    if name in {"accepted", "qualified", "review-received", "testimonial-received"}:
        return "#16a34a"
    if name in {"not-fit", "do-not-contact"}:
        return "#dc2626"
    if name in {"agency", "media-buyer", "lead-gen-agency", "founding-partner"}:
        return "#7c3aed"
    if name in {"hvac", "roofing", "restoration", "solar"}:
        return "#ea580c"
    return "#2563eb"


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Set up Prestyj founding cohort CRM assets without sending messages."
    )
    parser.add_argument(
        "--workspace-id",
        type=uuid.UUID,
        default=DEFAULT_WORKSPACE_ID,
        help="Workspace UUID to set up. Defaults to DEFAULT_WORKSPACE_ID or app default.",
    )
    parser.add_argument(
        "--frontend-url",
        default=settings.frontend_url,
        help="Frontend URL used when printing public offer links.",
    )
    parser.add_argument(
        "--imessage-sender",
        default=None,
        help="Optional E.164 Mac relay iMessage sender to upsert and use for draft campaigns.",
    )
    parser.add_argument(
        "--mac-relay-sender-id",
        default=None,
        help="Optional provider sender ID for the Mac relay sender identity.",
    )
    parser.add_argument(
        "--voice-sender",
        default=None,
        help="Optional E.164 Telnyx voice sender to use for the draft voice campaign.",
    )
    parser.add_argument(
        "--no-campaign-drafts",
        action="store_true",
        help="Skip draft campaign creation even if senders are available.",
    )
    return parser.parse_args()


def print_report(report: SetupReport) -> None:
    """Print a concise setup report."""
    print("Prestyj founding cohort setup complete.")
    _print_section("Offers", report.offers)
    _print_section("Agents", report.agents)
    _print_section("Tags", [f"{len(report.tags)} tags ready"])
    _print_section("Pipeline", [report.pipeline] if report.pipeline else [])
    _print_section("Message templates", report.message_templates)
    _print_section("iMessage sender", [report.phone_number] if report.phone_number else [])
    _print_section("Draft campaigns", report.campaigns)
    _print_section("Skipped", report.skipped)


def _print_section(title: str, lines: list[str]) -> None:
    """Print one report section."""
    if not lines:
        return
    print(f"\n{title}:")
    for line in lines:
        print(f"  - {line}")


def main() -> None:
    """Run the setup from the command line."""
    args = parse_args()
    report = asyncio.run(
        setup_prestyj_founding_cohort(
            workspace_id=args.workspace_id,
            frontend_url=str(args.frontend_url),
            imessage_sender=args.imessage_sender,
            mac_relay_sender_id=args.mac_relay_sender_id,
            voice_sender=args.voice_sender,
            create_campaign_drafts=not bool(args.no_campaign_drafts),
        )
    )
    print_report(report)


if __name__ == "__main__":
    main()
