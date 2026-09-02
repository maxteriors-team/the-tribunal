"""The tool schemas must express closed value sets as enums, not as prose.

With the value set described only in a description string, the model guessed.
The worst case was ``list_campaigns(status="active")`` — a natural guess that
is not a real status — which returned ``success: true, total: 0`` and became
"you have no active campaigns". An enum makes that a schema error instead.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.models.campaign import CampaignStatus
from app.schemas.offer import DiscountType, GuaranteeType, UrgencyType
from app.services.ai.crm_assistant._tools import (
    CRM_ASSISTANT_AUTOMATION_ACTION_TYPES,
    CRM_ASSISTANT_AUTOMATION_TRIGGER_TYPES,
    CRM_TOOLS,
    get_crm_tools,
)

_TOOLS = {tool["function"]["name"]: tool["function"] for tool in get_crm_tools()}


def _schema(tool: str, *path: str) -> dict[str, Any]:
    node = _TOOLS[tool]["parameters"]
    for key in path:
        node = node["properties"][key] if key != "[]" else node["items"]
    return node


def _walk_objects(schema: Any, path: str = "") -> list[tuple[str, dict[str, Any]]]:
    found: list[tuple[str, dict[str, Any]]] = []
    if not isinstance(schema, dict):
        return found
    if schema.get("type") == "object":
        found.append((path, schema))
    for key, child in (schema.get("properties") or {}).items():
        found.extend(_walk_objects(child, f"{path}.{key}"))
    if isinstance(schema.get("items"), dict):
        found.extend(_walk_objects(schema["items"], f"{path}[]"))
    for keyword in ("allOf", "anyOf", "oneOf"):
        for index, variant in enumerate(schema.get(keyword) or []):
            found.extend(_walk_objects(variant, f"{path}.{keyword}[{index}]"))
    return found


class TestEnums:
    def test_campaign_status_is_a_real_enum(self) -> None:
        schema = _schema("list_campaigns", "status")

        assert schema["enum"] == [status.value for status in CampaignStatus]

    def test_the_natural_wrong_guess_is_not_a_valid_status(self) -> None:
        """'active' is what a model reaches for; it is not a campaign status."""
        assert "active" not in _schema("list_campaigns", "status")["enum"]

    def test_automation_trigger_enum_only_exposes_runtime_supported_values(self) -> None:
        values = _schema("create_automation", "trigger_type")["enum"]

        assert values == list(CRM_ASSISTANT_AUTOMATION_TRIGGER_TYPES)
        assert not {"event", "generic_event", "schedule", "condition"}.intersection(values)

    def test_automation_action_type_only_exposes_canonical_values(self) -> None:
        values = _schema("create_automation", "actions", "[]", "type")["enum"]

        assert values == list(CRM_ASSISTANT_AUTOMATION_ACTION_TYPES)
        assert "add_tag" not in values
        assert "delay" not in values

    @pytest.mark.parametrize("tool", ["create_agent", "update_agent"])
    def test_channel_mode_is_enumerated(self, tool: str) -> None:
        assert _schema(tool, "channel_mode")["enum"] == ["voice", "text", "both"]

    def test_voice_provider_is_enumerated(self) -> None:
        assert _schema("create_agent", "voice_provider")["enum"] == ["openai", "elevenlabs"]

    @pytest.mark.parametrize("tool", ["create_offer_draft", "update_offer_draft"])
    def test_offer_enums_track_their_schema_types(self, tool: str) -> None:
        assert _schema(tool, "discount_type")["enum"] == [item.value for item in DiscountType]
        assert _schema(tool, "guarantee_type")["enum"] == [item.value for item in GuaranteeType]
        assert _schema(tool, "urgency_type")["enum"] == [item.value for item in UrgencyType]

    def test_enum_coverage_is_far_above_the_single_enum_baseline(self) -> None:
        payload = json.dumps(get_crm_tools())

        assert payload.count('"enum"') >= 10


class TestContactContextSnapshot:
    def test_requires_a_resolved_contact_id_and_bounds_timeline_pages(self) -> None:
        parameters = _TOOLS["get_contact_context"]["parameters"]

        assert parameters["required"] == ["contact_id"]
        assert _schema("get_contact_context", "contact_id")["minimum"] == 1
        assert _schema("get_contact_context", "timeline_limit")["maximum"] == 50
        assert _schema("get_contact_context", "timeline_offset")["maximum"] == 10_000

    def test_description_requires_identity_resolution_and_timestamp_citations(self) -> None:
        description = _TOOLS["get_contact_context"]["description"]

        assert "search_contacts" in description
        assert "provenance.updated_at" in description
        assert "workspace context" in description


class TestStrictSchemas:
    def test_top_level_parameters_are_openai_compatible(self) -> None:
        parameters = {
            tool["function"]["name"]: tool["function"]["parameters"] for tool in get_crm_tools()
        }
        assert {
            name: schema.get("type")
            for name, schema in parameters.items()
            if schema.get("type") != "object"
        } == {}

        forbidden = {"allOf", "anyOf", "oneOf", "enum", "const", "not"}
        violations = {
            name: sorted(forbidden.intersection(schema))
            for name, schema in parameters.items()
            if forbidden.intersection(schema)
        }
        assert violations == {}

    def test_closed_objects_forbid_unknown_keys(self) -> None:
        for tool in get_crm_tools():
            for path, schema in _walk_objects(
                tool["function"]["parameters"], tool["function"]["name"]
            ):
                if "properties" not in schema:
                    continue
                assert schema.get("additionalProperties") is False, path

    def test_no_argument_tools_reject_every_key(self) -> None:
        for name in ("get_dashboard_stats", "get_today_queue"):
            assert _TOOLS[name]["parameters"]["additionalProperties"] is False

    def test_automation_config_variants_are_closed(self) -> None:
        trigger_config = _schema("create_automation", "trigger_config")
        action_item = _schema("create_automation", "actions", "[]")

        assert trigger_config["anyOf"]
        assert all(variant["additionalProperties"] is False for variant in trigger_config["anyOf"])
        assert action_item["anyOf"]
        assert all(
            variant["properties"]["config"]["additionalProperties"] is False
            for variant in action_item["anyOf"]
        )

    def test_every_automation_action_has_one_closed_config_variant(self) -> None:
        action_item = _schema("create_automation", "actions", "[]")
        covered = [
            action_type
            for variant in action_item["anyOf"]
            for action_type in variant["properties"]["type"]["enum"]
        ]

        assert sorted(covered) == sorted(CRM_ASSISTANT_AUTOMATION_ACTION_TYPES)
        assert len(covered) == len(set(covered))
        for variant in action_item["anyOf"]:
            assert variant["properties"]["config"]["additionalProperties"] is False

    def test_branch_schema_has_step_ids_strict_filters_and_targets(self) -> None:
        action_item = _schema("create_automation", "actions", "[]")
        branch = next(
            variant
            for variant in action_item["anyOf"]
            if variant["properties"]["type"]["enum"] == ["branch"]
        )
        config = branch["properties"]["config"]

        assert "id" in action_item["properties"]
        assert config["required"] == ["condition", "then_goto", "else_goto"]
        assert config["properties"]["condition"]["properties"]["rules"]["minItems"] == 1
        assert config["properties"]["condition"]["additionalProperties"] is False

    @pytest.mark.parametrize("tool", ["create_automation", "update_automation"])
    def test_automation_drafts_cannot_set_active_state(self, tool: str) -> None:
        assert "is_active" not in _TOOLS[tool]["parameters"]["properties"]

    def test_nested_array_item_objects_are_hardened(self) -> None:
        item = _schema("create_offer_draft", "value_stack_items", "[]")

        assert item["additionalProperties"] is False

    def test_hardening_does_not_mutate_the_source_definitions(self) -> None:
        """get_crm_tools() returns copies; CRM_TOOLS must stay pristine."""
        get_crm_tools()
        source = next(tool for tool in CRM_TOOLS if tool["function"]["name"] == "list_campaigns")

        assert "additionalProperties" not in source["function"]["parameters"]

    def test_required_fields_all_exist_as_properties(self) -> None:
        for tool in get_crm_tools():
            parameters = tool["function"]["parameters"]
            properties = parameters.get("properties", {})
            for field in parameters.get("required", []):
                assert field in properties, f"{tool['function']['name']}.{field}"
