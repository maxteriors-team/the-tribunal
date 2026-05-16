"""Tests for the generic ``filter_rules`` / ``filter_logic`` engine.

These tests exercise the shared helpers in
``app.services._filters.base`` against a real SQLAlchemy ``Select`` to
confirm the produced expressions compile to the SQL we expect and that
unknown fields/operators are silently skipped.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Integer, String, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql.elements import ColumnElement

from app.services._filters import (
    apply_filter_rules,
    build_condition,
)


class _Base(DeclarativeBase):
    pass


class _Thing(_Base):
    __tablename__ = "things"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    score: Mapped[int] = mapped_column(Integer)
    bucket: Mapped[str] = mapped_column(String(50))


_COLUMN_MAP: dict[str, Any] = {
    "name": _Thing.name,
    "score": _Thing.score,
    "bucket": _Thing.bucket,
}


def _compile(stmt: Any) -> str:
    return str(
        stmt.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


class TestBuildCondition:
    """Operator-only translation: ``(operator, column, value) -> expr``."""

    def test_equals(self) -> None:
        expr = build_condition("equals", _Thing.score, 5)
        assert expr is not None
        assert "things.score = 5" in _compile(select(_Thing).where(expr))

    def test_not_equals(self) -> None:
        expr = build_condition("not_equals", _Thing.score, 5)
        assert expr is not None
        assert "things.score != 5" in _compile(select(_Thing).where(expr))

    def test_contains_uses_ilike_with_percent_wildcards(self) -> None:
        expr = build_condition("contains", _Thing.name, "ada")
        assert expr is not None
        sql = _compile(select(_Thing).where(expr))
        assert "ILIKE" in sql.upper()
        assert "%ada%" in sql

    def test_starts_with(self) -> None:
        expr = build_condition("starts_with", _Thing.name, "ad")
        assert expr is not None
        sql = _compile(select(_Thing).where(expr))
        assert "ad%" in sql

    def test_ends_with(self) -> None:
        expr = build_condition("ends_with", _Thing.name, "da")
        assert expr is not None
        sql = _compile(select(_Thing).where(expr))
        assert "%da" in sql

    @pytest.mark.parametrize(
        ("operator", "fragment"),
        [
            ("gt", ">"),
            ("gte", ">="),
            ("lt", "<"),
            ("lte", "<="),
            ("after", ">="),
            ("before", "<="),
        ],
    )
    def test_numeric_operators(self, operator: str, fragment: str) -> None:
        expr = build_condition(operator, _Thing.score, 10)
        assert expr is not None
        sql = _compile(select(_Thing).where(expr))
        assert f"things.score {fragment} 10" in sql

    def test_in_requires_list(self) -> None:
        expr = build_condition("in", _Thing.bucket, ["a", "b"])
        assert expr is not None
        sql = _compile(select(_Thing).where(expr))
        assert "IN" in sql.upper()

    def test_in_with_non_list_returns_none(self) -> None:
        assert build_condition("in", _Thing.bucket, "a") is None

    def test_not_in(self) -> None:
        expr = build_condition("not_in", _Thing.bucket, ["a", "b"])
        assert expr is not None
        sql = _compile(select(_Thing).where(expr))
        assert "NOT IN" in sql.upper()

    def test_is_null_and_is_not_null(self) -> None:
        is_null = build_condition("is_null", _Thing.name, None)
        is_not_null = build_condition("is_not_null", _Thing.name, None)
        assert is_null is not None and is_not_null is not None
        assert "IS NULL" in _compile(select(_Thing).where(is_null)).upper()
        assert "IS NOT NULL" in _compile(select(_Thing).where(is_not_null)).upper()

    def test_unknown_operator_returns_none(self) -> None:
        assert build_condition("matches_regex", _Thing.name, ".*") is None


class TestApplyFilterRules:
    """End-to-end: rule list -> narrowed ``Select`` statement."""

    def test_empty_rules_returns_query_unchanged(self) -> None:
        base = select(_Thing)
        out = apply_filter_rules(base, [], "and", _COLUMN_MAP)
        assert _compile(out) == _compile(base)

    def test_all_unsupported_rules_return_query_unchanged(self) -> None:
        base = select(_Thing)
        rules = [{"field": "nope", "operator": "equals", "value": 1}]
        out = apply_filter_rules(base, rules, "and", _COLUMN_MAP)
        assert _compile(out) == _compile(base)

    def test_and_logic_combines_with_and(self) -> None:
        rules = [
            {"field": "score", "operator": "gte", "value": 10},
            {"field": "bucket", "operator": "equals", "value": "vip"},
        ]
        out = apply_filter_rules(select(_Thing), rules, "and", _COLUMN_MAP)
        sql = _compile(out)
        assert "things.score >= 10" in sql
        assert "things.bucket = 'vip'" in sql
        assert " AND " in sql.upper()

    def test_or_logic_combines_with_or(self) -> None:
        rules = [
            {"field": "score", "operator": "gte", "value": 10},
            {"field": "bucket", "operator": "equals", "value": "vip"},
        ]
        out = apply_filter_rules(select(_Thing), rules, "or", _COLUMN_MAP)
        sql = _compile(out)
        assert " OR " in sql.upper()

    def test_unknown_field_is_skipped_but_others_still_apply(self) -> None:
        rules = [
            {"field": "totally_made_up", "operator": "equals", "value": 1},
            {"field": "score", "operator": "gte", "value": 10},
        ]
        out = apply_filter_rules(select(_Thing), rules, "and", _COLUMN_MAP)
        sql = _compile(out)
        assert "things.score >= 10" in sql
        assert "totally_made_up" not in sql

    def test_unknown_operator_is_skipped(self) -> None:
        rules = [
            {"field": "score", "operator": "matches_regex", "value": ".*"},
            {"field": "score", "operator": "gte", "value": 10},
        ]
        out = apply_filter_rules(select(_Thing), rules, "and", _COLUMN_MAP)
        sql = _compile(out)
        assert "things.score >= 10" in sql

    def test_extra_resolver_handles_non_column_fields(self) -> None:
        def resolver(field: str, operator: str, value: Any) -> ColumnElement[bool] | None:
            if field == "magic" and operator == "equals":
                return _Thing.bucket == f"magic-{value}"
            return None

        rules = [{"field": "magic", "operator": "equals", "value": "x"}]
        out = apply_filter_rules(select(_Thing), rules, "and", _COLUMN_MAP, extra_resolver=resolver)
        sql = _compile(out)
        assert "things.bucket = 'magic-x'" in sql

    def test_extra_resolver_returning_none_is_skipped(self) -> None:
        def resolver(_field: str, _operator: str, _value: Any) -> ColumnElement[bool] | None:
            return None

        rules = [{"field": "magic", "operator": "equals", "value": "x"}]
        base = select(_Thing)
        out = apply_filter_rules(base, rules, "and", _COLUMN_MAP, extra_resolver=resolver)
        assert _compile(out) == _compile(base)

    def test_column_map_takes_precedence_over_extra_resolver(self) -> None:
        def resolver(_field: str, _operator: str, _value: Any) -> ColumnElement[bool] | None:
            raise AssertionError("extra_resolver should not be called for mapped field")

        rules = [{"field": "score", "operator": "equals", "value": 1}]
        out = apply_filter_rules(select(_Thing), rules, "and", _COLUMN_MAP, extra_resolver=resolver)
        assert "things.score = 1" in _compile(out)

    def test_missing_field_and_operator_keys_are_safe(self) -> None:
        base = select(_Thing)
        out = apply_filter_rules(base, [{}], "and", _COLUMN_MAP)
        assert _compile(out) == _compile(base)
