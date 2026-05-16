"""Generic filter-rule helpers shared across resource filter engines.

This package houses the reusable building blocks for translating
``filter_rules`` / ``filter_logic`` JSON definitions into SQLAlchemy
conditions. Concrete filter modules (contacts, campaigns, opportunities,
...) define a ``column_map`` and optional ``extra_resolver`` and delegate
the rule-evaluation work to :func:`apply_filter_rules`.
"""

from app.services._filters.base import (
    ExtraResolver,
    apply_filter_rules,
    build_condition,
)

__all__ = ["ExtraResolver", "apply_filter_rules", "build_condition"]
