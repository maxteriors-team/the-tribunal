"""CRM assistant tool definitions for OpenAI function calling.

Style: short imperative descriptions, only non-obvious params documented.
Mirrors the prompt-hint style in ezcoder's tools/prompt-hints.ts.
"""

from copy import deepcopy
from typing import Any

from app.core.permissions import role_can
from app.models.campaign import CampaignContactStatus, CampaignStatus, CampaignType
from app.schemas.automation import AUTOMATION_ACTION_TYPES, AUTOMATION_TRIGGER_TYPES
from app.schemas.offer import DiscountType, GuaranteeType, UrgencyType
from app.services.ai.crm_assistant._tool_metadata import tool_capability
from app.services.campaigns.audience_service import MAX_CAMPAIGN_AUDIENCE_SIZE
from app.services.contacts.contact_filter_validation import (
    CONTACT_FILTER_ENUM_VALUES,
    MAX_CONTACT_FILTER_RULES,
    MAX_FILTER_LIST_VALUES,
)

# ── Closed value sets ────────────────────────────────────────────────
# These used to live only in prose descriptions, so the model guessed. The
# worst case was `list_campaigns(status="active")` — not a real status —
# returning `success: true, total: 0`, which the model reported as "you have
# no active campaigns". An enum turns that guess into a hard schema error.
CAMPAIGN_STATUSES = [status.value for status in CampaignStatus]
CAMPAIGN_TYPES = [campaign_type.value for campaign_type in CampaignType]
CAMPAIGN_CONTACT_STATUSES = [status.value for status in CampaignContactStatus]
CHANNEL_MODES = ["voice", "text", "both"]
VOICE_PROVIDERS = ["openai", "elevenlabs"]
DISCOUNT_TYPES = [discount.value for discount in DiscountType]
GUARANTEE_TYPES = [guarantee.value for guarantee in GuaranteeType]
URGENCY_TYPES = [urgency.value for urgency in UrgencyType]
CONTACT_STATUSES = ["new", "contacted", "qualified", "converted", "lost"]
CONTACT_TAG_MATCH_MODES = ["any", "all", "none"]
CRM_ASSISTANT_AUTOMATION_TRIGGER_TYPES = tuple(
    trigger
    for trigger in AUTOMATION_TRIGGER_TYPES
    if trigger not in {"event", "generic_event", "schedule", "condition"}
)
CRM_ASSISTANT_AUTOMATION_ACTION_TYPES = tuple(
    action for action in AUTOMATION_ACTION_TYPES if action not in {"add_tag", "delay"}
)


def _filter_rule_variant(
    fields: list[str],
    operators: list[str],
    *,
    value_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "field": {"type": "string", "enum": fields},
        "operator": {"type": "string", "enum": operators},
    }
    required = ["field", "operator"]
    if value_schema is not None:
        properties["value"] = value_schema
        required.append("value")
    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }


def _contact_filter_rules_schema() -> dict[str, Any]:
    text = {"type": "string", "minLength": 1, "maxLength": 500}
    number = {"type": "number", "minimum": 0, "maximum": 1_000_000_000}
    string_list = {
        "type": "array",
        "items": text,
        "minItems": 1,
        "maxItems": MAX_FILTER_LIST_VALUES,
        "uniqueItems": True,
    }
    variants = [
        _filter_rule_variant(["source"], ["equals", "contains"], value_schema=text),
        _filter_rule_variant(["source"], ["in"], value_schema=string_list),
        _filter_rule_variant(
            ["lead_score", "engagement_score", "noshow_count"],
            ["equals", "gt", "gte", "lt", "lte"],
            value_schema=number,
        ),
        _filter_rule_variant(
            [
                "is_qualified",
                "qualification_signals.budget",
                "qualification_signals.authority",
                "qualification_signals.need",
                "qualification_signals.timeline",
            ],
            ["is_true", "is_false"],
        ),
        _filter_rule_variant(
            ["created_at", "last_engaged_at"],
            ["before", "after"],
            value_schema={"type": "string", "minLength": 1, "maxLength": 50},
        ),
        _filter_rule_variant(
            ["created_at", "last_engaged_at"],
            ["is_null", "is_not_null"],
        ),
        _filter_rule_variant(
            ["tags"],
            ["has_any", "has_all"],
            value_schema={
                "type": "array",
                "items": {"type": "string", "format": "uuid"},
                "minItems": 1,
                "maxItems": MAX_FILTER_LIST_VALUES,
                "uniqueItems": True,
            },
        ),
    ]
    for field in (
        "status",
        "enrichment_status",
        "sms_consent_status",
        "last_appointment_status",
    ):
        values = sorted(CONTACT_FILTER_ENUM_VALUES[field])
        variants.extend(
            [
                _filter_rule_variant(
                    [field],
                    ["equals"],
                    value_schema={"type": "string", "enum": values},
                ),
                _filter_rule_variant(
                    [field],
                    ["in"],
                    value_schema={
                        "type": "array",
                        "items": {"type": "string", "enum": values},
                        "minItems": 1,
                        "maxItems": len(values),
                        "uniqueItems": True,
                    },
                ),
            ]
        )
    variants.append(_filter_rule_variant(["last_appointment_status"], ["is_null", "is_not_null"]))
    return {
        "type": "array",
        "minItems": 1,
        "maxItems": MAX_CONTACT_FILTER_RULES,
        "items": {"oneOf": variants},
    }


def _opportunity_write_properties() -> dict[str, Any]:
    return {
        "name": {"type": "string", "minLength": 1, "maxLength": 255},
        "description": {"type": "string", "maxLength": 5_000},
        "amount": {"type": "number", "minimum": 0},
        "currency": {"type": "string", "pattern": "^[A-Z]{3}$"},
        "expected_close_date": {"type": "string", "format": "date"},
        "source": {"type": "string", "maxLength": 255},
        "status": {"type": "string", "enum": ["open", "won", "lost", "abandoned"]},
        "lost_reason": {"type": "string", "maxLength": 2_000},
        "stage_id": {"type": "string", "format": "uuid"},
        "primary_contact_id": {"type": ["integer", "null"], "minimum": 1},
        "assigned_user_id": {"type": ["integer", "null"], "minimum": 1},
    }


def _closed_config(
    *,
    properties: dict[str, Any],
    required: list[str] | None = None,
    description: str,
    any_of: list[dict[str, Any]] | None = None,
    one_of: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "description": description,
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    if any_of:
        schema["anyOf"] = any_of
    if one_of:
        schema["oneOf"] = one_of
    return schema


def _automation_trigger_config_schema() -> dict[str, Any]:
    """Describe the configuration keys understood by each automation trigger."""

    return {
        "type": "object",
        "description": (
            "Configuration for the selected trigger. Use the matching variant only; "
            "all triggers not named below use an empty object."
        ),
        "anyOf": [
            _closed_config(
                description="contact_tagged: match contacts carrying this exact tag",
                properties={"tag": {"type": "string", "minLength": 1}},
                required=["tag"],
            ),
            _closed_config(
                description="never_booked: optionally override the default 7-day inactivity",
                properties={"inactivity_days": {"type": "integer", "minimum": 1, "maximum": 3650}},
            ),
            _closed_config(
                description=(
                    "backlog_below_threshold: fire when weeks of booked work drop under "
                    "threshold_weeks (4 is typical for home services), then stay silent for "
                    "cooldown_days so a slow month cannot re-blast the same audience"
                ),
                properties={
                    "threshold_weeks": {"type": "number", "exclusiveMinimum": 0, "maximum": 104},
                    "cooldown_days": {"type": "integer", "minimum": 1, "maximum": 365},
                },
                required=["threshold_weeks", "cooldown_days"],
            ),
            _closed_config(
                description=(
                    "lead_created: optionally match one or more lead-source selectors "
                    "(OR semantics)"
                ),
                properties={
                    "lead_source_public_key": {"type": "string", "minLength": 1},
                    "lead_source_id": {"type": "string", "format": "uuid"},
                    "source_detail": {"type": "string", "minLength": 1},
                },
            ),
            _closed_config(
                description="job_completed: optionally restrict to lighting projects",
                properties={"lighting_project_only": {"type": "boolean"}},
            ),
            _closed_config(
                description="All other triggers: pass an empty object",
                properties={},
            ),
        ],
    }


def _automation_action_variant(
    action_types: list[str],
    *,
    config: dict[str, Any],
    description: str,
) -> dict[str, Any]:
    return {
        "type": "object",
        "description": description,
        "properties": {
            "id": {
                "type": "string",
                "pattern": "^[A-Za-z][A-Za-z0-9_-]{0,63}$",
            },
            "type": {"type": "string", "enum": action_types},
            "config": config,
        },
        "required": ["type", "config"],
    }


def _automation_actions_schema() -> dict[str, Any]:
    """Return action variants tied to the exact config their worker consumes."""

    fallbacks = {
        "type": "object",
        "description": "Optional template-token fallback strings",
        "additionalProperties": {"type": "string"},
    }
    action_variants = [
        _automation_action_variant(
            ["send_sms"],
            description="Send an SMS to the matched contact",
            config=_closed_config(
                description="SMS template configuration",
                properties={
                    "message": {"type": "string", "minLength": 1},
                    "agent_id": {"type": "string", "format": "uuid"},
                    "require_consent": {"type": "boolean"},
                    "fallbacks": fallbacks,
                },
                required=["message"],
            ),
        ),
        _automation_action_variant(
            ["send_email"],
            description="Send an email to the matched contact",
            config=_closed_config(
                description="Email subject and body templates",
                properties={
                    "subject": {"type": "string", "minLength": 1},
                    "message": {"type": "string", "minLength": 1},
                    "fallbacks": fallbacks,
                },
                required=["subject", "message"],
            ),
        ),
        _automation_action_variant(
            ["make_call"],
            description="Place an outbound AI voice call",
            config=_closed_config(
                description="Optional workspace voice agent; provider setup stays admin-managed",
                properties={"agent_id": {"type": "string", "format": "uuid"}},
            ),
        ),
        _automation_action_variant(
            ["enroll_campaign"],
            description="Enroll the matched contact in a running or scheduled campaign",
            config=_closed_config(
                description="Target campaign",
                properties={"campaign_id": {"type": "string", "format": "uuid"}},
                required=["campaign_id"],
            ),
        ),
        _automation_action_variant(
            ["start_drip_campaign"],
            description="Start a reactivation drip sequence for the workspace",
            config=_closed_config(
                description="Target drip campaign",
                properties={
                    "drip_campaign_id": {"type": "string", "format": "uuid"},
                    "enroll_contact": {
                        "type": "boolean",
                        "description": (
                            "Also enroll the matched contact (default true; ignored when the "
                            "trigger has no contact)"
                        ),
                    },
                },
                required=["drip_campaign_id"],
            ),
        ),
        _automation_action_variant(
            ["move_to_stage"],
            description=(
                "Create the matched contact's open opportunity at a pipeline stage when "
                "that pipeline has no open deal; otherwise move the existing open opportunity"
            ),
            config=_closed_config(
                description="Destination pipeline stage",
                properties={
                    "stage_id": {"type": "string", "format": "uuid"},
                    "pipeline_id": {
                        "type": "string",
                        "format": "uuid",
                        "description": "Optional pipeline UUID; it must own the selected stage",
                    },
                },
                required=["stage_id"],
            ),
        ),
        _automation_action_variant(
            ["apply_tag"],
            description="Apply a workspace tag to the matched contact",
            config=_closed_config(
                description="Tag to apply",
                properties={"tag": {"type": "string", "minLength": 1, "maxLength": 100}},
                required=["tag"],
            ),
        ),
        _automation_action_variant(
            ["wait"],
            description="Pause the action sequence, then resume later",
            config=_closed_config(
                description="Exactly one positive duration, bounded to 365 days",
                properties={
                    "minutes": {"type": "integer", "minimum": 1, "maximum": 525_600},
                    "hours": {"type": "integer", "minimum": 1, "maximum": 8_760},
                    "days": {"type": "integer", "minimum": 1, "maximum": 365},
                },
                one_of=[
                    {"required": ["minutes"]},
                    {"required": ["hours"]},
                    {"required": ["days"]},
                ],
            ),
        ),
        _automation_action_variant(
            ["branch"],
            description="Route a contact based on strict contact-filter rules",
            config=_closed_config(
                description="Condition and explicit destination step IDs",
                properties={
                    "condition": {
                        "type": "object",
                        "properties": {
                            "logic": {"type": "string", "enum": ["and", "or"]},
                            "rules": _contact_filter_rules_schema(),
                        },
                        "required": ["rules"],
                    },
                    "then_goto": {
                        "type": "string",
                        "pattern": "^(?:__end__|[A-Za-z][A-Za-z0-9_-]{0,63})$",
                    },
                    "else_goto": {
                        "type": "string",
                        "pattern": "^(?:__end__|[A-Za-z][A-Za-z0-9_-]{0,63})$",
                    },
                },
                required=["condition", "then_goto", "else_goto"],
            ),
        ),
    ]
    return {
        "type": "array",
        "description": "Actions run in order when the trigger fires",
        "minItems": 1,
        "maxItems": 50,
        "items": {
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "pattern": "^[A-Za-z][A-Za-z0-9_-]{0,63}$",
                },
                "type": {
                    "type": "string",
                    "enum": list(CRM_ASSISTANT_AUTOMATION_ACTION_TYPES),
                },
                "config": {"type": "object"},
            },
            "required": ["type", "config"],
            "anyOf": action_variants,
        },
    }


def _harden_object_schema(schema: dict[str, Any]) -> None:
    """Recursively forbid unknown keys on every closed object schema.

    Object schemas that omit ``properties`` entirely are intentionally open.
    Variant branches are traversed so per-type automation configs are closed too.
    """

    if schema.get("type") == "object" and "properties" in schema:
        schema.setdefault("additionalProperties", False)
        for child in schema["properties"].values():
            if isinstance(child, dict):
                _harden_object_schema(child)
    items = schema.get("items")
    if isinstance(items, dict):
        _harden_object_schema(items)
    for keyword in ("allOf", "anyOf", "oneOf"):
        variants = schema.get(keyword)
        if isinstance(variants, list):
            for variant in variants:
                if isinstance(variant, dict):
                    _harden_object_schema(variant)


def _apply_tool_policy_metadata(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return hardened copies of the OpenAI tool definitions."""

    hardened: list[dict[str, Any]] = []
    for tool in tools:
        copied = deepcopy(tool)
        parameters = copied["function"].setdefault("parameters", {})
        _harden_object_schema(parameters)
        hardened.append(copied)
    return hardened


CRM_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_contacts",
            "description": (
                "Resolve contact identity before any contact-specific state or history lookup. "
                "Name and company match partial text; encrypted phone/email require the complete "
                "value. The result includes identity_resolution: resolved, ambiguous, or "
                "not_found. If ambiguous, ask the operator to choose; never guess. Once resolved, "
                "call get_contact_context with that contact_id. Use an empty query only to list "
                "the newest contacts."
            ),
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
            "name": "get_contact",
            "description": (
                "Legacy narrow contact-row lookup for mutation preparation. Do not use it to "
                "answer questions about a contact's current state or history; after resolving "
                "identity, use get_contact_context instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "contact_id": {"type": "integer", "minimum": 1},
                    "include_timeline": {
                        "type": "boolean",
                        "description": "Include recent messages and calls (default false)",
                    },
                    "timeline_limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 50,
                        "description": "Timeline rows when included (default 20)",
                    },
                },
                "required": ["contact_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_contact_context",
            "description": (
                "Read-only authoritative snapshot for one resolved contact_id in this workspace. "
                "In one call it returns identity, lifecycle and consent, qualification, tags, "
                "attribution, campaign enrollments, open opportunities, active quotes/invoices, "
                "appointments, notes, and a bounded chronological SMS/voice/voicemail timeline. "
                "Resolve names, phone numbers, or email addresses with search_contacts first; "
                "never choose among ambiguous matches. Use timeline_offset with next_offset to "
                "page older events. Base current-state claims on the structured snapshot, not "
                "workspace context, notes, or message text, and cite observed_at plus the relevant "
                "provenance.updated_at timestamp in the answer."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "contact_id": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Resolved workspace contact id",
                    },
                    "timeline_limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 50,
                        "description": "Cross-channel events in this page (default 20, max 50)",
                    },
                    "timeline_offset": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 10000,
                        "description": (
                            "Newer events to skip when paging backward; use the prior next_offset"
                        ),
                    },
                },
                "required": ["contact_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_contact",
            "description": (
                "Update fields on an existing contact. This edits the record in place; "
                "never create a replacement contact. Use add_contact_note and "
                "add_contact_tags for additive notes/tags."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "contact_id": {"type": "integer", "minimum": 1},
                    "first_name": {"type": "string", "minLength": 1, "maxLength": 100},
                    "last_name": {"type": "string", "maxLength": 100},
                    "email": {"type": "string", "format": "email"},
                    "phone_number": {
                        "type": "string",
                        "description": "Complete phone number; E.164 preferred",
                    },
                    "company_name": {"type": "string", "maxLength": 255},
                    "address_line1": {"type": "string", "maxLength": 255},
                    "address_line2": {"type": "string", "maxLength": 255},
                    "address_city": {"type": "string", "maxLength": 100},
                    "address_state": {"type": "string", "maxLength": 50},
                    "address_zip": {"type": "string", "maxLength": 20},
                    "status": {"type": "string", "enum": CONTACT_STATUSES},
                    "lead_score": {"type": "integer", "minimum": 0},
                    "important_dates": {
                        "type": "object",
                        "description": "Birthday, anniversary, or named dates",
                    },
                },
                "required": ["contact_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_contact_note",
            "description": (
                "Append a timestamped note to a contact without overwriting existing notes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "contact_id": {"type": "integer", "minimum": 1},
                    "note": {"type": "string", "minLength": 1, "maxLength": 5000},
                },
                "required": ["contact_id", "note"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_contact_tags",
            "description": (
                "Idempotently add tags to one contact. Existing tags are preserved; "
                "missing workspace tags are created."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "contact_id": {"type": "integer", "minimum": 1},
                    "tags": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1, "maxLength": 100},
                        "minItems": 1,
                        "maxItems": 20,
                    },
                },
                "required": ["contact_id", "tags"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_contacts",
            "description": (
                "Find contacts with structured filters: tags, lifecycle status, score, "
                "qualification, source/company, created dates, or last-contacted dates. "
                "Use search_contacts for name/phone/email text lookups. Returns truthful "
                "returned/total/has_more counts."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filters": {
                        "type": "object",
                        "properties": {
                            "tags": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Workspace tag names, not ids",
                            },
                            "tags_match": {
                                "type": "string",
                                "enum": CONTACT_TAG_MATCH_MODES,
                                "description": "Match any, all, or none of the tags",
                            },
                            "status": {"type": "string", "enum": CONTACT_STATUSES},
                            "lead_score_min": {"type": "integer", "minimum": 0},
                            "lead_score_max": {"type": "integer", "minimum": 0},
                            "is_qualified": {"type": "boolean"},
                            "source": {"type": "string"},
                            "company_name": {"type": "string"},
                            "created_after": {
                                "type": "string",
                                "description": "ISO date/datetime, inclusive",
                            },
                            "created_before": {
                                "type": "string",
                                "description": "ISO date/datetime, inclusive",
                            },
                            "last_engaged_before": {
                                "type": "string",
                                "description": "ISO date/datetime; finds stale contacts",
                            },
                            "last_engaged_after": {
                                "type": "string",
                                "description": "ISO date/datetime",
                            },
                            "not_contacted_days": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": 3650,
                                "description": "No engagement in this many days",
                            },
                            "include_never_contacted": {
                                "type": "boolean",
                                "description": "Include contacts with no engagement (default true)",
                            },
                            "enrichment_status": {"type": "string"},
                        },
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 50,
                        "description": "Max rows returned (default 20)",
                    },
                },
                "required": ["filters"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_tags",
            "description": "List workspace tag IDs and names for saved audience filters.",
            "parameters": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 100}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_segments",
            "description": "List reusable saved contact audiences in this workspace.",
            "parameters": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 50}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "preview_segment",
            "description": (
                "Return the current matching count and a bounded contact sample for one "
                "saved audience. Preview before campaign enrollment."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "segment_id": {"type": "string", "format": "uuid"},
                    "sample_limit": {"type": "integer", "minimum": 1, "maximum": 25},
                },
                "required": ["segment_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_segment",
            "description": (
                "Create a dynamic saved audience from strict contact filters. Use list_tags "
                "for tag UUIDs. This only saves targeting rules; it sends nothing."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "minLength": 1, "maxLength": 255},
                    "description": {"type": "string", "maxLength": 2000},
                    "filter_logic": {"type": "string", "enum": ["and", "or"]},
                    "filter_rules": _contact_filter_rules_schema(),
                },
                "required": ["name", "filter_rules"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_segment",
            "description": (
                "Update a saved audience and recompute its current count. Use list_tags "
                "for tag UUIDs."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "segment_id": {"type": "string", "format": "uuid"},
                    "name": {"type": "string", "minLength": 1, "maxLength": 255},
                    "description": {"type": ["string", "null"], "maxLength": 2000},
                    "filter_logic": {"type": "string", "enum": ["and", "or"]},
                    "filter_rules": _contact_filter_rules_schema(),
                },
                "required": ["segment_id"],
                "anyOf": [
                    {"required": ["name"]},
                    {"required": ["description"]},
                    {"required": ["filter_logic"]},
                    {"required": ["filter_rules"]},
                ],
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
                        "enum": CAMPAIGN_STATUSES,
                        "description": "Filter to one campaign status",
                    },
                    "limit": {"type": "integer", "description": "Max results (default 10)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_campaign",
            "description": (
                "Create a draft campaign without enrolling contacts or sending anything. "
                "For SMS/voice, from_phone_number defaults to the workspace's first active "
                "sender. Email campaigns require email_subject. Review the returned draft "
                "before separately starting it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "minLength": 1, "maxLength": 255},
                    "campaign_type": {"type": "string", "enum": CAMPAIGN_TYPES},
                    "agent_id": {"type": "string", "format": "uuid"},
                    "offer_id": {"type": "string", "format": "uuid"},
                    "from_phone_number": {
                        "type": "string",
                        "description": (
                            "Workspace-owned sender; omit to choose the first active sender"
                        ),
                    },
                    "initial_message": {
                        "type": "string",
                        "minLength": 1,
                        "description": "SMS text or email body; supports {first_name}",
                    },
                    "email_subject": {"type": "string", "minLength": 1},
                    "ai_enabled": {"type": "boolean"},
                    "qualification_criteria": {"type": "string"},
                    "scheduled_start": {"type": "string", "format": "date-time"},
                    "sending_hours_start": {
                        "type": "string",
                        "pattern": "^([01]\\d|2[0-3]):[0-5]\\d$",
                    },
                    "sending_hours_end": {
                        "type": "string",
                        "pattern": "^([01]\\d|2[0-3]):[0-5]\\d$",
                    },
                    "sending_days": {
                        "type": "array",
                        "items": {"type": "integer", "minimum": 0, "maximum": 6},
                        "uniqueItems": True,
                    },
                    "timezone": {"type": "string"},
                    "messages_per_minute": {"type": "integer", "minimum": 1, "maximum": 100},
                    "follow_up_enabled": {"type": "boolean"},
                    "follow_up_delay_hours": {"type": "integer", "minimum": 1},
                    "follow_up_message": {"type": "string"},
                    "max_follow_ups": {"type": "integer", "minimum": 0, "maximum": 10},
                    "guarantee_target": {"type": "integer", "minimum": 1},
                    "guarantee_window_days": {"type": "integer", "minimum": 1},
                },
                "required": ["name", "campaign_type", "initial_message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_campaign",
            "description": (
                "Edit an existing draft or paused campaign in place, including its "
                "initial_message before launch. Does not start or resume the campaign."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "campaign_id": {"type": "string", "format": "uuid"},
                    "name": {"type": "string", "minLength": 1, "maxLength": 255},
                    "agent_id": {"type": "string", "format": "uuid"},
                    "offer_id": {"type": "string", "format": "uuid"},
                    "from_phone_number": {"type": "string"},
                    "initial_message": {"type": "string", "minLength": 1},
                    "email_subject": {"type": "string", "minLength": 1},
                    "ai_enabled": {"type": "boolean"},
                    "qualification_criteria": {"type": "string"},
                    "scheduled_start": {"type": "string", "format": "date-time"},
                    "sending_hours_start": {
                        "type": "string",
                        "pattern": "^([01]\\d|2[0-3]):[0-5]\\d$",
                    },
                    "sending_hours_end": {
                        "type": "string",
                        "pattern": "^([01]\\d|2[0-3]):[0-5]\\d$",
                    },
                    "sending_days": {
                        "type": "array",
                        "items": {"type": "integer", "minimum": 0, "maximum": 6},
                        "uniqueItems": True,
                    },
                    "timezone": {"type": "string"},
                    "messages_per_minute": {"type": "integer", "minimum": 1, "maximum": 100},
                    "follow_up_enabled": {"type": "boolean"},
                    "follow_up_delay_hours": {"type": "integer", "minimum": 1},
                    "follow_up_message": {"type": "string"},
                    "max_follow_ups": {"type": "integer", "minimum": 0, "maximum": 10},
                    "guarantee_target": {"type": "integer", "minimum": 1},
                    "guarantee_window_days": {"type": "integer", "minimum": 1},
                },
                "required": ["campaign_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "enroll_campaign_audience",
            "description": (
                "Enroll one validated segment or explicit contact list into a draft campaign. "
                "Existing enrollments are deduplicated, contacts missing the campaign channel "
                "are counted and skipped, and no outreach is sent."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "campaign_id": {"type": "string", "format": "uuid"},
                    "segment_id": {"type": "string", "format": "uuid"},
                    "contact_ids": {
                        "type": "array",
                        "items": {"type": "integer", "minimum": 1},
                        "minItems": 1,
                        "maxItems": MAX_CAMPAIGN_AUDIENCE_SIZE,
                        "uniqueItems": True,
                    },
                },
                "required": ["campaign_id"],
                "oneOf": [
                    {"required": ["segment_id"]},
                    {"required": ["contact_ids"]},
                ],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_campaign_contacts",
            "description": (
                "List people enrolled in one campaign with contact ids, names, phone/email, "
                "delivery/reply status, qualification, opt-out, and truthful total count."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "campaign_id": {"type": "string", "format": "uuid"},
                    "status": {"type": "string", "enum": CAMPAIGN_CONTACT_STATUSES},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                },
                "required": ["campaign_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_agents",
            "description": (
                "List AI agents with their current system prompts, channels, model settings, "
                "enabled tools, and active state. Read before updating an agent."
            ),
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
            "name": "get_agent",
            "description": "Get one AI agent's current system prompt and editable settings.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "Agent UUID"},
                },
                "required": ["agent_id"],
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
            "name": "list_automations",
            "description": "List workflow automations (trigger → actions) in the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "active_only": {"type": "boolean", "description": "Only active automations"},
                    "limit": {"type": "integer", "description": "Max results (default 10)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_automation",
            "description": (
                "Get one automation's complete trigger, ordered actions, active state, "
                "and execution timestamps. Use before changing or deleting it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "automation_id": {"type": "string", "description": "Automation UUID"},
                },
                "required": ["automation_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_automation",
            "description": (
                "Create an inactive workflow draft with executable triggers and ordered actions. "
                "Use enable_automation separately after reviewing it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "minLength": 1},
                    "description": {"type": "string"},
                    "trigger_type": {
                        "type": "string",
                        "enum": list(CRM_ASSISTANT_AUTOMATION_TRIGGER_TYPES),
                        "description": "Runtime-supported event or condition trigger.",
                    },
                    "trigger_config": _automation_trigger_config_schema(),
                    "actions": _automation_actions_schema(),
                },
                "required": ["name", "trigger_type", "actions"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_automation",
            "description": (
                "Edit an inactive automation draft. Disable active automations first. Replacing "
                "actions requires the complete ordered list; activation remains separate."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "automation_id": {"type": "string", "description": "Automation UUID"},
                    "name": {"type": "string", "minLength": 1},
                    "description": {"type": ["string", "null"]},
                    "trigger_type": {
                        "type": "string",
                        "enum": list(CRM_ASSISTANT_AUTOMATION_TRIGGER_TYPES),
                    },
                    "trigger_config": _automation_trigger_config_schema(),
                    "actions": _automation_actions_schema(),
                },
                "required": ["automation_id"],
                "anyOf": [
                    {"required": ["name"]},
                    {"required": ["description"]},
                    {"required": ["trigger_type"]},
                    {"required": ["trigger_config"]},
                    {"required": ["actions"]},
                ],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "enable_automation",
            "description": (
                "Enable an automation so its trigger starts firing (can send messages); "
                "requires explicit confirmation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "automation_id": {"type": "string", "description": "Automation UUID"},
                },
                "required": ["automation_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "disable_automation",
            "description": "Disable an automation so it stops firing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "automation_id": {"type": "string", "description": "Automation UUID"},
                },
                "required": ["automation_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_automation",
            "description": (
                "Permanently delete an automation after reading it with get_automation. "
                "Requires explicit confirmation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "automation_id": {"type": "string", "description": "Automation UUID"},
                },
                "required": ["automation_id"],
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
                    "channel_mode": {"type": "string", "enum": CHANNEL_MODES},
                    "voice_provider": {"type": "string", "enum": VOICE_PROVIDERS},
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
                    "channel_mode": {"type": "string", "enum": CHANNEL_MODES},
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
            "description": (
                "Legacy narrow message lookup for conversation operations. For any question about "
                "one contact's communication history or follow-up state, use get_contact_context "
                "so SMS, voice, voicemail, and current CRM state arrive together."
            ),
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
            "description": (
                "Workspace-wide calendar filtering by contact, status, or ISO 8601 date range. "
                "For a resolved contact's complete current state, use get_contact_context."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "contact_id": {"type": "integer"},
                    "status": {
                        "type": "string",
                        "enum": ["scheduled", "completed", "cancelled", "no_show"],
                    },
                    "date_from": {"type": "string", "description": "ISO 8601 start datetime"},
                    "date_to": {"type": "string", "description": "ISO 8601 end datetime"},
                    "include_past": {"type": "boolean", "description": "Include past events"},
                    "limit": {"type": "integer", "description": "Max results (default 10)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_appointment",
            "description": "Get one calendar appointment before changing or deleting it.",
            "parameters": {
                "type": "object",
                "properties": {"appointment_id": {"type": "integer"}},
                "required": ["appointment_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_appointment",
            "description": (
                "Schedule a calendar appointment for a CRM contact. Resolve ambiguous contacts "
                "with find_contacts first. Requires human approval."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "contact_id": {"type": "integer"},
                    "scheduled_at": {
                        "type": "string",
                        "description": "ISO 8601 datetime with offset",
                    },
                    "duration_minutes": {"type": "integer", "minimum": 15, "maximum": 480},
                    "service_type": {"type": "string", "maxLength": 100},
                    "notes": {"type": "string"},
                    "agent_id": {"type": "string", "description": "Optional agent UUID"},
                },
                "required": ["contact_id", "scheduled_at"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_appointment",
            "description": (
                "Reschedule, cancel, complete, or edit a calendar appointment after reading it. "
                "Requires human approval."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "appointment_id": {"type": "integer"},
                    "scheduled_at": {
                        "type": "string",
                        "description": "ISO 8601 datetime with offset",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["scheduled", "completed", "cancelled", "no_show"],
                    },
                    "duration_minutes": {"type": "integer", "minimum": 15, "maximum": 480},
                    "service_type": {"type": "string", "maxLength": 100},
                    "notes": {"type": "string"},
                },
                "required": ["appointment_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_appointment",
            "description": (
                "Permanently delete a calendar appointment after reading it. "
                "Requires human approval."
            ),
            "parameters": {
                "type": "object",
                "properties": {"appointment_id": {"type": "integer"}},
                "required": ["appointment_id"],
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
            "name": "list_pipeline_stages",
            "description": (
                "List workspace pipeline and stage names with their UUIDs in stage order. "
                "Use this to resolve stage_id and pipeline_id before creating stage actions. "
                "Optional name filters are case-insensitive partial matches."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pipeline_name": {
                        "type": "string",
                        "description": "Optional pipeline name filter",
                    },
                    "stage_name": {
                        "type": "string",
                        "description": "Optional stage name filter",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_opportunities",
            "description": (
                "List visible pipeline opportunities. Sales reps see only opportunities assigned "
                "to themselves; managers and admins see the workspace."
            ),
            "parameters": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 50}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_opportunity",
            "description": (
                "Get one visible opportunity with its activities and tasks. Sales reps may only "
                "open opportunities assigned to themselves."
            ),
            "parameters": {
                "type": "object",
                "properties": {"opportunity_id": {"type": "string", "format": "uuid"}},
                "required": ["opportunity_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_opportunity",
            "description": (
                "Create a pipeline opportunity using existing workspace resources. Sales reps "
                "are always assigned as the owner, regardless of assigned_user_id."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pipeline_id": {"type": "string", "format": "uuid"},
                    **_opportunity_write_properties(),
                },
                "required": ["pipeline_id", "name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_opportunity",
            "description": (
                "Update a visible opportunity without deleting it. Sales reps may only update "
                "their own opportunities and remain self-assigned."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "opportunity_id": {"type": "string", "format": "uuid"},
                    **_opportunity_write_properties(),
                },
                "required": ["opportunity_id"],
                "anyOf": [{"required": [field]} for field in _opportunity_write_properties()],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_offers",
            "description": (
                "List workspace offer definitions for outbound campaigns; this is not evidence "
                "of a specific contact's quote or current state. Use get_contact_context for that."
            ),
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
                    "discount_type": {"type": "string", "enum": DISCOUNT_TYPES},
                    "discount_value": {"type": "number"},
                    "terms": {"type": "string"},
                    "headline": {"type": "string"},
                    "subheadline": {"type": "string"},
                    "regular_price": {"type": "number"},
                    "offer_price": {"type": "number"},
                    "savings_amount": {"type": "number"},
                    "guarantee_type": {"type": "string", "enum": GUARANTEE_TYPES},
                    "guarantee_days": {"type": "integer"},
                    "guarantee_text": {"type": "string"},
                    "urgency_type": {"type": "string", "enum": URGENCY_TYPES},
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
                    "discount_type": {"type": "string", "enum": DISCOUNT_TYPES},
                    "discount_value": {"type": "number"},
                    "terms": {"type": "string"},
                    "is_active": {"type": "boolean"},
                    "headline": {"type": "string"},
                    "subheadline": {"type": "string"},
                    "regular_price": {"type": "number"},
                    "offer_price": {"type": "number"},
                    "savings_amount": {"type": "number"},
                    "guarantee_type": {"type": "string", "enum": GUARANTEE_TYPES},
                    "guarantee_days": {"type": "integer"},
                    "guarantee_text": {"type": "string"},
                    "urgency_type": {"type": "string", "enum": URGENCY_TYPES},
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
    {
        "type": "function",
        "function": {
            "name": "search_help",
            "description": (
                "Search the bundled product-help source for any CRM screen or workflow, "
                "including exact UI labels, routes, supported actions, and limitations. "
                "Call it first for every product 'how do I', 'where do I', 'what's the "
                "difference', or 'does the system' question instead of answering from "
                "memory. Never create a record to demonstrate an answer. Use only the "
                "returned passages, preserve their labels and routes exactly, and say "
                "the workflow is not documented as supported when the passages do not "
                "answer the question. Returns ranked passages with help titles and sources."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "minLength": 1,
                        "description": "The operator's question, in their words",
                    },
                    "top_k": {"type": "integer", "minimum": 1, "maximum": 8},
                },
                "required": ["query"],
            },
        },
    },
]


def get_crm_tools() -> list[dict[str, Any]]:
    """Return the full CRM tool catalog for OpenAI function calling.

    This is the unfiltered catalog. Anything that actually talks to a model on
    behalf of a user must call :func:`tools_for_role` instead.
    """
    return _apply_tool_policy_metadata(CRM_TOOLS)


def tools_for_role(role: str) -> list[dict[str, Any]]:
    """Return only the tool definitions ``role`` is allowed to run.

    Withholding a schema keeps the model from proposing an action the caller
    cannot take, which is a UX and token win rather than a control: the binding
    check is in :meth:`CRMToolExecutor.execute`, which re-tests the same
    capability on every call. A field technician gets an empty list.
    """
    return [
        tool
        for tool in get_crm_tools()
        if role_can(role, tool_capability(tool["function"]["name"]))
    ]
