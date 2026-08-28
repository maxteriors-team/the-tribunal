"""Fail-closed validation for model-authored contact filter rules."""

from __future__ import annotations

import math
import uuid
from datetime import datetime
from typing import Any

MAX_CONTACT_FILTER_RULES = 25
MAX_FILTER_LIST_VALUES = 100

CONTACT_FILTER_OPERATORS: dict[str, frozenset[str]] = {
    "status": frozenset({"equals", "in"}),
    "source": frozenset({"equals", "contains", "in"}),
    "lead_score": frozenset({"equals", "gt", "gte", "lt", "lte"}),
    "engagement_score": frozenset({"equals", "gt", "gte", "lt", "lte"}),
    "is_qualified": frozenset({"is_true", "is_false"}),
    "enrichment_status": frozenset({"equals", "in"}),
    "sms_consent_status": frozenset({"equals", "in"}),
    "created_at": frozenset({"before", "after", "is_null", "is_not_null"}),
    "last_engaged_at": frozenset({"before", "after", "is_null", "is_not_null"}),
    "tags": frozenset({"has_any", "has_all"}),
    "noshow_count": frozenset({"equals", "gt", "gte", "lt", "lte"}),
    "last_appointment_status": frozenset({"equals", "in", "is_null", "is_not_null"}),
    "qualification_signals.budget": frozenset({"is_true", "is_false"}),
    "qualification_signals.authority": frozenset({"is_true", "is_false"}),
    "qualification_signals.need": frozenset({"is_true", "is_false"}),
    "qualification_signals.timeline": frozenset({"is_true", "is_false"}),
}

CONTACT_FILTER_ENUM_VALUES: dict[str, frozenset[str]] = {
    "status": frozenset({"new", "contacted", "qualified", "converted", "lost"}),
    "enrichment_status": frozenset({"pending", "enriched", "failed", "skipped"}),
    "sms_consent_status": frozenset({"unknown", "opted_in", "opted_out"}),
    "last_appointment_status": frozenset({"scheduled", "completed", "cancelled", "no_show"}),
}
_NUMERIC_FIELDS = frozenset({"lead_score", "engagement_score", "noshow_count"})
_DATE_FIELDS = frozenset({"created_at", "last_engaged_at"})
_VALUELESS_OPERATORS = frozenset({"is_true", "is_false", "is_null", "is_not_null"})


class ContactFilterValidationError(ValueError):
    """Raised when an untrusted contact filter is not exactly supported."""


def _validate_string(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise ContactFilterValidationError(f"{field} requires a non-empty string value")
    return value.strip()


def _validate_enum(value: object, *, field: str) -> str:
    text = _validate_string(value, field=field)
    if text not in CONTACT_FILTER_ENUM_VALUES[field]:
        raise ContactFilterValidationError(f"{field} has an unsupported value")
    return text


def _validate_list(value: object, *, field: str) -> list[str]:
    if not isinstance(value, list) or not value or len(value) > MAX_FILTER_LIST_VALUES:
        raise ContactFilterValidationError(
            f"{field} requires between 1 and {MAX_FILTER_LIST_VALUES} values"
        )
    if field == "tags":
        try:
            normalized = [str(uuid.UUID(str(item))) for item in value]
        except (TypeError, ValueError, AttributeError) as exc:
            raise ContactFilterValidationError("tags requires valid tag UUIDs") from exc
    elif field in CONTACT_FILTER_ENUM_VALUES:
        normalized = [_validate_enum(item, field=field) for item in value]
    else:
        normalized = [_validate_string(item, field=field) for item in value]
    if len(normalized) != len(set(normalized)):
        raise ContactFilterValidationError(f"{field} values must be unique")
    return normalized


def _validated_value(field: str, operator: str, value: object) -> Any:
    if operator in _VALUELESS_OPERATORS:
        if value is not None:
            raise ContactFilterValidationError(f"{operator} does not accept a value")
        return None
    if operator in {"in", "has_any", "has_all"}:
        return _validate_list(value, field=field)
    if field in _NUMERIC_FIELDS:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ContactFilterValidationError(f"{field} requires a numeric value")
        if (
            isinstance(value, float) and not math.isfinite(value)
        ) or not 0 <= value <= 1_000_000_000:
            raise ContactFilterValidationError(
                f"{field} requires a finite value between 0 and 1,000,000,000"
            )
        return value
    if field in _DATE_FIELDS:
        text = _validate_string(value, field=field)
        try:
            datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ContactFilterValidationError(f"{field} requires an ISO 8601 value") from exc
        return text
    if field in CONTACT_FILTER_ENUM_VALUES:
        return _validate_enum(value, field=field)
    return _validate_string(value, field=field)


def validate_contact_filter_rules(
    filter_rules: object,
    filter_logic: object = "and",
    *,
    require_rules: bool = True,
) -> tuple[list[dict[str, Any]], str]:
    """Validate and normalize the reusable contact-filter language.

    Unsupported fields, operators, values, and extra keys are rejected rather
    than passed to ``apply_contact_filters``, where they would otherwise be
    ignored and could broaden a model-authored audience.
    """

    if not isinstance(filter_logic, str) or filter_logic.lower() not in {"and", "or"}:
        raise ContactFilterValidationError("filter_logic must be 'and' or 'or'")
    logic = filter_logic.lower()
    if not isinstance(filter_rules, list):
        raise ContactFilterValidationError("filter_rules must be a list")
    if require_rules and not filter_rules:
        raise ContactFilterValidationError("filter_rules must contain at least one rule")
    if len(filter_rules) > MAX_CONTACT_FILTER_RULES:
        raise ContactFilterValidationError(
            f"filter_rules cannot contain more than {MAX_CONTACT_FILTER_RULES} rules"
        )

    validated: list[dict[str, Any]] = []
    for rule in filter_rules:
        if not isinstance(rule, dict) or set(rule) - {"field", "operator", "value"}:
            raise ContactFilterValidationError("each filter rule must contain only supported keys")
        field = rule.get("field")
        operator = rule.get("operator")
        if not isinstance(field, str) or field not in CONTACT_FILTER_OPERATORS:
            raise ContactFilterValidationError("filter rule has an unsupported field")
        if not isinstance(operator, str) or operator not in CONTACT_FILTER_OPERATORS[field]:
            raise ContactFilterValidationError(f"{field} has an unsupported operator")

        normalized: dict[str, Any] = {"field": field, "operator": operator}
        value = _validated_value(field, operator, rule.get("value"))
        if operator not in _VALUELESS_OPERATORS:
            normalized["value"] = value
        validated.append(normalized)

    return validated, logic
