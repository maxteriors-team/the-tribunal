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
from app.schemas.automation import AUTOMATION_ACTION_TYPES, AUTOMATION_TRIGGER_TYPES
from app.schemas.offer import DiscountType, GuaranteeType, UrgencyType
from app.services.ai.crm_assistant._tools import CRM_TOOLS, get_crm_tools

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
    return found


class TestEnums:
    def test_campaign_status_is_a_real_enum(self) -> None:
        schema = _schema("list_campaigns", "status")

        assert schema["enum"] == [status.value for status in CampaignStatus]

    def test_the_natural_wrong_guess_is_not_a_valid_status(self) -> None:
        """'active' is what a model reaches for; it is not a campaign status."""
        assert "active" not in _schema("list_campaigns", "status")["enum"]

    def test_automation_trigger_enum_tracks_the_schema_constant(self) -> None:
        assert _schema("create_automation", "trigger_type")["enum"] == list(
            AUTOMATION_TRIGGER_TYPES
        )

    def test_automation_action_type_is_enumerated(self) -> None:
        schema = _schema("create_automation", "actions", "[]", "type")

        assert schema["enum"] == list(AUTOMATION_ACTION_TYPES)

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


class TestStrictSchemas:
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

    def test_free_form_config_objects_stay_open(self) -> None:
        """Locking these would forbid every key and break the tool."""
        assert "additionalProperties" not in _schema("create_automation", "trigger_config")
        assert "additionalProperties" not in _schema("create_automation", "actions", "[]", "config")

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
