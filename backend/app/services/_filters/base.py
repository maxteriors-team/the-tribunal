"""Generic ``filter_rules`` / ``filter_logic`` engine.

This module owns the operator vocabulary used by every JSON-rule filter
engine in the codebase. Resource-specific filter modules supply a
``column_map`` (field name -> SQLAlchemy column) and, when they need to
handle non-column fields such as tag membership, an ``extra_resolver``.

The split mirrors what was previously inlined inside
``contact_filters.py``:

* :func:`build_condition` is operator-only — given a column and a value,
  it returns a SQLAlchemy expression.
* :func:`apply_filter_rules` walks the rule list, resolves each rule's
  ``field`` against the ``column_map`` (falling back to
  ``extra_resolver`` when present), and combines the resulting
  expressions with ``and_``/``or_`` depending on ``logic``.
"""

from __future__ import annotations

from typing import Any, Protocol, cast

from sqlalchemy import Select, and_, or_
from sqlalchemy.sql.elements import ColumnElement


class ExtraResolver(Protocol):
    """Resolver for non-column fields (e.g. ``tags`` membership).

    Returns a SQLAlchemy expression or ``None`` if the field/operator
    combination is not supported.
    """

    def __call__(self, field: str, operator: str, value: Any) -> ColumnElement[bool] | None: ...


def build_condition(
    operator: str,
    column: Any,
    value: Any,
) -> ColumnElement[bool] | None:
    """Translate a single ``(operator, column, value)`` triple.

    Supported operators are the union of the operators previously used by
    every resource-specific engine. Returns ``None`` for unknown
    operators so callers can decide whether to skip silently or raise.
    """
    if operator == "in" and isinstance(value, list):
        return cast("ColumnElement[bool]", column.in_(value))
    if operator == "not_in" and isinstance(value, list):
        return cast("ColumnElement[bool]", column.notin_(value))

    comparison_ops: dict[str, Any] = {
        "equals": lambda c, v: c == v,
        "not_equals": lambda c, v: c != v,
        "contains": lambda c, v: c.ilike(f"%{v}%"),
        "starts_with": lambda c, v: c.ilike(f"{v}%"),
        "ends_with": lambda c, v: c.ilike(f"%{v}"),
        "gte": lambda c, v: c >= v,
        "lte": lambda c, v: c <= v,
        "gt": lambda c, v: c > v,
        "lt": lambda c, v: c < v,
        "after": lambda c, v: c >= v,
        "before": lambda c, v: c <= v,
        "is_true": lambda c, _v: c.is_(True),
        "is_false": lambda c, _v: c.is_(False),
        "is_null": lambda c, _v: c.is_(None),
        "is_not_null": lambda c, _v: c.isnot(None),
    }

    op_fn = comparison_ops.get(operator)
    if op_fn is None:
        return None
    return cast("ColumnElement[bool]", op_fn(column, value))


def apply_filter_rules(
    query: Select[Any],
    rules: list[dict[str, Any]],
    logic: str,
    column_map: dict[str, Any],
    extra_resolver: ExtraResolver | None = None,
) -> Select[Any]:
    """Apply a list of ``{field, operator, value}`` rules to ``query``.

    Args:
        query: A SQLAlchemy ``Select`` statement to narrow.
        rules: Rule dicts as produced by ``FilterDefinition``.
        logic: ``"and"`` (default) or ``"or"`` — how to combine rules.
        column_map: Mapping from rule ``field`` strings to SQLAlchemy
            columns. Fields not in the map fall through to
            ``extra_resolver``.
        extra_resolver: Optional callable for non-column fields such as
            tag membership. Returns a SQLAlchemy expression or ``None``.

    Returns:
        The query narrowed by the combined rule expression. If no rule
        produced a usable condition the query is returned unchanged.
    """
    conditions: list[ColumnElement[bool]] = []

    for rule in rules:
        field = rule.get("field", "")
        operator = rule.get("operator", "")
        value = rule.get("value")

        condition: ColumnElement[bool] | None = None
        column = column_map.get(field)
        if column is not None:
            condition = build_condition(operator, column, value)
        elif extra_resolver is not None:
            condition = extra_resolver(field, operator, value)

        if condition is not None:
            conditions.append(condition)

    if not conditions:
        return query

    combined = or_(*conditions) if logic == "or" else and_(*conditions)
    return query.where(combined)
