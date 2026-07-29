"""Golden set of operator utterances mapped to the tool the assistant should pick.

This is the accuracy contract for the CRM assistant. Unlike the unit tests in
``tests/test_crm_assistant_*.py`` — which script the tool call and therefore
cannot detect a wrong tool choice — every case here is scored against a real
model call over the real tool schemas.

Cases intentionally reference tools that do not exist yet (``get_contact``,
``update_campaign``, ``search_help``, ...). Those categories score zero at
baseline; that zero is the measurement that justifies building them.

Scoring rules per case:
- ``expected_tools``  — calling any one of these counts as correct.
- ``forbidden_tools`` — calling any of these fails the case outright, even if
  an expected tool was also called. Used for destructive look-alikes ("how do
  I set up an automation?" must not *create* one).
- ``expect_no_tool``  — the correct behaviour is to answer without tools.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class GoldenCase:
    """One operator utterance and the tool choice that would satisfy it."""

    id: str
    category: str
    utterance: str
    expected_tools: tuple[str, ...] = ()
    forbidden_tools: tuple[str, ...] = ()
    expect_no_tool: bool = False
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.expected_tools and not self.expect_no_tool:
            raise ValueError(f"Golden case {self.id} has no expected outcome")


# ── Contact lookup ───────────────────────────────────────────────────
_CONTACT_LOOKUP: tuple[GoldenCase, ...] = (
    GoldenCase(
        id="lookup_by_phone",
        category="contact_lookup",
        utterance="Look up the customer with phone number +15554829910.",
        expected_tools=("search_contacts", "find_contacts"),
        notes="Bug A: encrypted phone column made this return zero matches.",
    ),
    GoldenCase(
        id="lookup_by_email",
        category="contact_lookup",
        utterance="Do we have anyone in the CRM with the email jenna.wills@gmail.com?",
        expected_tools=("search_contacts", "find_contacts"),
    ),
    GoldenCase(
        id="lookup_by_name",
        category="contact_lookup",
        utterance="Pull up Bob Marchetti's record for me.",
        expected_tools=("search_contacts", "get_contact", "find_contacts"),
    ),
    GoldenCase(
        id="lookup_total_contacts",
        category="contact_lookup",
        utterance="How many contacts do I have in total?",
        expected_tools=("get_dashboard_stats", "search_contacts", "find_contacts"),
    ),
    GoldenCase(
        id="lookup_newest_leads",
        category="contact_lookup",
        utterance="Show me the five newest leads that came in.",
        expected_tools=("search_contacts", "find_contacts"),
    ),
    GoldenCase(
        id="lookup_by_company",
        category="contact_lookup",
        utterance="Find the contact at Ridgeline Property Group.",
        expected_tools=("search_contacts", "find_contacts"),
    ),
)

# ── Contact writes (the "adding contact information" ask) ────────────
_CONTACT_WRITE: tuple[GoldenCase, ...] = (
    GoldenCase(
        id="write_create_contact",
        category="contact_write",
        utterance=(
            "Add a new contact: Maria Delgado, phone +15558675309, email maria.delgado@example.com."
        ),
        expected_tools=("create_contact",),
    ),
    GoldenCase(
        id="write_update_email",
        category="contact_write",
        utterance="Update contact 4821's email address to newaddress@example.com.",
        expected_tools=("update_contact",),
        forbidden_tools=("create_contact",),
        notes="Without update_contact the model duplicates the record.",
    ),
    GoldenCase(
        id="write_add_note",
        category="contact_write",
        utterance=(
            "Add a note on contact 3310: he wants a quote for gutter cleaning in the spring."
        ),
        expected_tools=("add_contact_note", "update_contact"),
        forbidden_tools=("create_contact", "send_sms"),
    ),
    GoldenCase(
        id="write_add_tag",
        category="contact_write",
        utterance="Tag contact 918 as hot-lead.",
        expected_tools=("add_contact_tags", "update_contact"),
        forbidden_tools=("create_automation",),
        notes="create_automation can apply tags; tagging one contact must not build a machine.",
    ),
    GoldenCase(
        id="write_get_contact_detail",
        category="contact_write",
        utterance="Show me everything you have on contact 512.",
        expected_tools=("get_contact", "search_contacts"),
    ),
    GoldenCase(
        id="write_set_status",
        category="contact_write",
        utterance="Mark contact 2044 as qualified.",
        expected_tools=("update_contact",),
        forbidden_tools=("create_contact",),
    ),
    GoldenCase(
        id="write_filter_stale",
        category="contact_write",
        utterance="Who haven't we contacted in the last 30 days?",
        expected_tools=("find_contacts", "search_contacts"),
    ),
    GoldenCase(
        id="write_filter_by_tag",
        category="contact_write",
        utterance="List everyone tagged hot-lead.",
        expected_tools=("find_contacts", "search_contacts"),
    ),
)

# ── Campaigns ────────────────────────────────────────────────────────
_CAMPAIGNS: tuple[GoldenCase, ...] = (
    GoldenCase(
        id="campaign_list_running",
        category="campaigns",
        utterance="What campaigns do I have running right now?",
        expected_tools=("list_campaigns",),
    ),
    GoldenCase(
        id="campaign_create",
        category="campaigns",
        utterance="Create a spring gutter cleaning campaign aimed at my past customers.",
        expected_tools=("create_campaign", "plan_outbound_growth_workflow"),
    ),
    GoldenCase(
        id="campaign_start",
        category="campaigns",
        utterance="Start my fall lighting campaign.",
        expected_tools=("start_campaign", "list_campaigns"),
    ),
    GoldenCase(
        id="campaign_pause",
        category="campaigns",
        utterance="Pause the reactivation campaign, it's sending too fast.",
        expected_tools=("pause_campaign", "list_campaigns"),
    ),
    GoldenCase(
        id="campaign_performance",
        category="campaigns",
        utterance="How did the June promo campaign perform?",
        expected_tools=("summarize_campaign", "list_campaigns"),
    ),
    GoldenCase(
        id="campaign_edit_message",
        category="campaigns",
        utterance="Change the opening message on my draft campaign before it goes out.",
        expected_tools=("update_campaign", "list_campaigns"),
        forbidden_tools=("start_campaign", "send_sms"),
    ),
    GoldenCase(
        id="campaign_enrolled_contacts",
        category="campaigns",
        utterance="Who is enrolled in the winter campaign?",
        expected_tools=("list_campaign_contacts", "list_campaigns"),
    ),
    GoldenCase(
        id="campaign_growth_plan",
        category="campaigns",
        utterance=("I want to run a reactivation blast to customers we haven't seen in a year."),
        expected_tools=("plan_outbound_growth_workflow", "create_campaign", "find_contacts"),
    ),
    GoldenCase(
        id="campaign_schedule_lookup",
        category="campaigns",
        utterance="When is my holiday lighting campaign scheduled to send?",
        expected_tools=("list_campaigns", "summarize_campaign"),
    ),
)

# ── Automations ──────────────────────────────────────────────────────
_AUTOMATIONS: tuple[GoldenCase, ...] = (
    GoldenCase(
        id="automation_list",
        category="automations",
        utterance="What automations do I have set up?",
        expected_tools=("list_automations",),
        forbidden_tools=("create_automation",),
    ),
    GoldenCase(
        id="automation_create",
        category="automations",
        utterance="Set up an automation that texts every new lead within five minutes.",
        expected_tools=("create_automation",),
    ),
    GoldenCase(
        id="automation_edit_wait",
        category="automations",
        utterance="Change the wait on my follow-up automation from 2 hours to 24 hours.",
        expected_tools=("update_automation", "get_automation", "list_automations"),
        forbidden_tools=("create_automation",),
        notes="Today the model must clone + disable, leaving junk behind.",
    ),
    GoldenCase(
        id="automation_disable",
        category="automations",
        utterance="Turn off the birthday automation.",
        expected_tools=("disable_automation", "list_automations"),
    ),
    GoldenCase(
        id="automation_delete",
        category="automations",
        utterance="Delete the old no-show follow-up automation, I don't use it anymore.",
        expected_tools=("delete_automation", "list_automations"),
    ),
    GoldenCase(
        id="automation_detail",
        category="automations",
        utterance="Show me exactly what my lead follow-up automation does.",
        expected_tools=("get_automation", "list_automations"),
        forbidden_tools=("create_automation",),
    ),
)

# ── Conversations ────────────────────────────────────────────────────
_CONVERSATIONS: tuple[GoldenCase, ...] = (
    GoldenCase(
        id="conversation_last_message",
        category="conversations",
        utterance="What did we last say to contact 771?",
        expected_tools=("get_conversation",),
        forbidden_tools=("send_sms",),
    ),
    GoldenCase(
        id="conversation_recent",
        category="conversations",
        utterance="Show me my most recent conversations.",
        expected_tools=("list_recent_conversations",),
    ),
    GoldenCase(
        id="conversation_replies_today",
        category="conversations",
        utterance="Has anybody replied to us today?",
        expected_tools=("list_recent_conversations",),
    ),
    GoldenCase(
        id="conversation_who_is_this",
        category="conversations",
        utterance=("Look at my latest conversation and tell me which customer it is with."),
        expected_tools=("list_recent_conversations", "get_contact", "search_contacts"),
        notes="Chain is structurally broken: no contact_id on the conversation payload.",
    ),
)

# ── Agents ───────────────────────────────────────────────────────────
_AGENTS: tuple[GoldenCase, ...] = (
    GoldenCase(
        id="agent_list",
        category="agents",
        utterance="What AI agents do I have?",
        expected_tools=("list_agents",),
        forbidden_tools=("create_agent",),
    ),
    GoldenCase(
        id="agent_read_prompt",
        category="agents",
        utterance="What are the instructions on my receptionist agent right now?",
        expected_tools=("get_agent", "list_agents"),
        forbidden_tools=("update_agent",),
        notes="update_agent can overwrite a prompt the model cannot read.",
    ),
    GoldenCase(
        id="agent_update_tone",
        category="agents",
        utterance="Make my receptionist agent sound friendlier on calls.",
        expected_tools=("update_agent", "get_agent", "list_agents"),
        forbidden_tools=("create_agent",),
    ),
)

# ── Pipeline, appointments, daily ops ────────────────────────────────
_OPERATIONS: tuple[GoldenCase, ...] = (
    GoldenCase(
        id="ops_pipeline",
        category="operations",
        utterance="What's in my pipeline right now?",
        expected_tools=("list_opportunities", "get_dashboard_stats"),
    ),
    GoldenCase(
        id="ops_appointments",
        category="operations",
        utterance="What appointments do I have coming up?",
        expected_tools=("list_appointments",),
    ),
    GoldenCase(
        id="ops_appointment_names",
        category="operations",
        utterance="Who are my appointments with tomorrow?",
        expected_tools=("list_appointments",),
        notes="Needs list_appointments → get_contact to name the person.",
    ),
    GoldenCase(
        id="ops_today_queue",
        category="operations",
        utterance="What should I do today?",
        expected_tools=("get_today_queue",),
    ),
    GoldenCase(
        id="ops_dashboard",
        category="operations",
        utterance="Give me the headline numbers for the business.",
        expected_tools=("get_dashboard_stats", "get_today_queue"),
    ),
)

# ── Offers ───────────────────────────────────────────────────────────
_OFFERS: tuple[GoldenCase, ...] = (
    GoldenCase(
        id="offer_list",
        category="offers",
        utterance="What offers do I have available?",
        expected_tools=("list_offers",),
    ),
    GoldenCase(
        id="offer_create_draft",
        category="offers",
        utterance="Draft a 20% off first-time exterior cleaning offer.",
        expected_tools=("create_offer_draft",),
    ),
)

# ── Product how-to / general CRM questions ───────────────────────────
_HOW_TO: tuple[GoldenCase, ...] = (
    GoldenCase(
        id="howto_setup_automation",
        category="how_to",
        utterance="How do I set up an automation in this CRM?",
        expected_tools=("search_help",),
        forbidden_tools=("create_automation",),
        notes="No product corpus exists, so today this is answered from model priors.",
    ),
    GoldenCase(
        id="howto_campaign_vs_automation",
        category="how_to",
        utterance="What's the difference between a campaign and an automation here?",
        expected_tools=("search_help",),
        forbidden_tools=("create_campaign", "create_automation"),
    ),
    GoldenCase(
        id="howto_approvals",
        category="how_to",
        utterance="How does the approval queue work?",
        expected_tools=("search_help",),
    ),
    GoldenCase(
        id="howto_add_phone_number",
        category="how_to",
        utterance="Where in the app do I add my sending phone number?",
        expected_tools=("search_help",),
    ),
    GoldenCase(
        id="howto_quiet_hours",
        category="how_to",
        utterance="Does the system respect quiet hours when it sends texts?",
        expected_tools=("search_help",),
        forbidden_tools=("send_sms",),
    ),
)


GOLDEN_SET: tuple[GoldenCase, ...] = (
    *_CONTACT_LOOKUP,
    *_CONTACT_WRITE,
    *_CAMPAIGNS,
    *_AUTOMATIONS,
    *_CONVERSATIONS,
    *_AGENTS,
    *_OPERATIONS,
    *_OFFERS,
    *_HOW_TO,
)


@dataclass(frozen=True, slots=True)
class GoldenSetStats:
    """Shape of the golden set, for sanity checks and report headers."""

    total: int
    categories: dict[str, int] = field(default_factory=dict)


def golden_set_stats(cases: tuple[GoldenCase, ...] = GOLDEN_SET) -> GoldenSetStats:
    """Return case counts overall and per category."""

    categories: dict[str, int] = {}
    for case in cases:
        categories[case.category] = categories.get(case.category, 0) + 1
    return GoldenSetStats(total=len(cases), categories=categories)


def cases_for_category(category: str) -> tuple[GoldenCase, ...]:
    """Return every golden case in one category."""

    return tuple(case for case in GOLDEN_SET if case.category == category)
