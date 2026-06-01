"""Generic filter-rule helpers shared across resource filter engines.

This package houses the reusable building blocks for translating
``filter_rules`` / ``filter_logic`` JSON definitions into SQLAlchemy
conditions. Concrete filter modules (contacts, campaigns, opportunities,
...) define a ``column_map`` and optional ``extra_resolver`` and delegate
the rule-evaluation work to :func:`apply_filter_rules`.
"""

from app.services._filters.base import (
    ExtraResolver,
    FilterSpec,
    apply_filter_rules,
    apply_filter_specs,
    apply_resource_filters,
    build_condition,
    contains_filter,
    presence_filter,
    range_filter_specs,
    search_filter,
)

__all__ = [
    "ExtraResolver",
    "FilterSpec",
    "apply_filter_rules",
    "apply_filter_specs",
    "apply_resource_filters",
    "build_condition",
    "contains_filter",
    "presence_filter",
    "range_filter_specs",
    "search_filter",
]
