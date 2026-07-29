"""Unit tests for :func:`app.services.quotes.attach_metrics.compute_attach_metrics`.

Pure and DB-free: the function takes anything with ``service_category`` and
``total``, so a dataclass stub exercises the whole rule set without Postgres.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.services.quotes.attach_metrics import compute_attach_metrics


@dataclass
class Line:
    """Minimal stand-in for a ``QuoteLineItem`` (category + line total)."""

    service_category: str | None
    total: float | Decimal | None


# --------------------------------------------------------------------------- #
# Empty / uncategorized quotes
# --------------------------------------------------------------------------- #
def test_empty_quote_has_no_metrics() -> None:
    """Nothing to group means nothing to report — not a zero-value roof job."""
    assert compute_attach_metrics([]) == (None, 0, 0.0)


def test_fully_uncategorized_quote_has_no_metrics() -> None:
    """Hand-typed lines never invent a primary service."""
    lines = [Line(None, 900.0), Line(None, 250.0)]

    assert compute_attach_metrics(lines) == (None, 0, 0.0)


def test_blank_category_is_treated_as_uncategorized() -> None:
    """A whitespace-only category must not become a phantom "" service."""
    lines = [Line("", 400.0), Line("   ", 100.0)]

    assert compute_attach_metrics(lines) == (None, 0, 0.0)


# --------------------------------------------------------------------------- #
# Single category
# --------------------------------------------------------------------------- #
def test_single_category_quote_has_no_attachments() -> None:
    lines = [Line("roof", 8000.0), Line("roof", 1200.0)]

    primary, attach_count, attach_value = compute_attach_metrics(lines)

    assert primary == "roof"
    assert attach_count == 0
    assert attach_value == 0.0


def test_repeated_category_counts_once() -> None:
    """Attach count is distinct categories, not distinct lines."""
    lines = [
        Line("roof", 9000.0),
        Line("gutters", 400.0),
        Line("gutters", 300.0),
        Line("gutters", 200.0),
    ]

    primary, attach_count, attach_value = compute_attach_metrics(lines)

    assert primary == "roof"
    assert attach_count == 1
    assert attach_value == 900.0


# --------------------------------------------------------------------------- #
# The canonical case: a roof job with a gutter attachment
# --------------------------------------------------------------------------- #
def test_roof_with_gutters_attaches_gutter_total() -> None:
    lines = [Line("roof", 12000.0), Line("gutters", 1500.0)]

    assert compute_attach_metrics(lines) == ("roof", 1, 1500.0)


def test_primary_is_the_largest_group_not_the_largest_line() -> None:
    """Three small roof lines outsell one big gutter line."""
    lines = [
        Line("roof", 3000.0),
        Line("roof", 3000.0),
        Line("roof", 3000.0),
        Line("gutters", 5000.0),
    ]

    assert compute_attach_metrics(lines) == ("roof", 1, 5000.0)


def test_multiple_attachments_sum_across_categories() -> None:
    lines = [
        Line("roof", 10000.0),
        Line("gutters", 1500.0),
        Line("siding", 2200.0),
        Line("windows", 300.0),
    ]

    primary, attach_count, attach_value = compute_attach_metrics(lines)

    assert primary == "roof"
    assert attach_count == 3
    assert attach_value == 4000.0


def test_line_order_does_not_change_the_answer() -> None:
    lines = [Line("gutters", 1500.0), Line("siding", 2200.0), Line("roof", 10000.0)]

    assert compute_attach_metrics(lines) == ("roof", 3 - 1, 3700.0)


# --------------------------------------------------------------------------- #
# Ties
# --------------------------------------------------------------------------- #
def test_tie_breaks_on_largest_single_line() -> None:
    """Equal category totals: the one with the biggest single line is primary."""
    lines = [
        Line("gutters", 500.0),
        Line("gutters", 500.0),
        Line("roof", 1000.0),
    ]

    primary, attach_count, attach_value = compute_attach_metrics(lines)

    assert primary == "roof"
    assert attach_count == 1
    assert attach_value == 1000.0


def test_tie_breaks_alphabetically_when_largest_lines_also_tie() -> None:
    """Fully symmetric quote: alphabetical order is the last resort, so the
    result stays deterministic instead of depending on insertion order."""
    lines = [Line("siding", 1000.0), Line("gutters", 1000.0)]

    assert compute_attach_metrics(lines) == ("gutters", 1, 1000.0)


def test_alphabetical_tie_break_is_order_independent() -> None:
    reversed_lines = [Line("gutters", 1000.0), Line("siding", 1000.0)]

    assert compute_attach_metrics(reversed_lines) == ("gutters", 1, 1000.0)


# --------------------------------------------------------------------------- #
# Mixed / messy input
# --------------------------------------------------------------------------- #
def test_null_categories_are_ignored_but_do_not_crash() -> None:
    """An uncategorized line stays out of the metrics even when it is the
    biggest line on the quote — it still counts toward the quote total, which
    is why attach_value is not simply "total minus primary"."""
    lines = [
        Line(None, 50000.0),
        Line("roof", 8000.0),
        Line("gutters", 1000.0),
    ]

    primary, attach_count, attach_value = compute_attach_metrics(lines)

    assert primary == "roof"
    assert attach_count == 1
    assert attach_value == 1000.0


def test_decimal_and_float_totals_group_identically() -> None:
    """Postgres Numeric hands back Decimal; unsaved objects hand back float."""
    lines = [Line("roof", Decimal("8000.50")), Line("gutters", 1000.25)]

    assert compute_attach_metrics(lines) == ("roof", 1, 1000.25)


def test_missing_total_is_treated_as_zero() -> None:
    """Metrics are a reporting side effect and must never block a save."""
    lines = [Line("roof", 500.0), Line("gutters", None)]

    assert compute_attach_metrics(lines) == ("roof", 1, 0.0)


def test_category_whitespace_is_normalized_before_grouping() -> None:
    """A padded category is the same service line, not a second one."""
    lines = [Line(" roof ", 4000.0), Line("roof", 4000.0), Line("gutters", 500.0)]

    primary, attach_count, attach_value = compute_attach_metrics(lines)

    assert primary == "roof"
    assert attach_count == 1
    assert attach_value == 500.0


def test_attach_value_is_rounded_to_cents() -> None:
    """Float summation must not leak 0.30000000000000004 into a money column."""
    lines = [Line("roof", 900.0), Line("gutters", 0.1), Line("siding", 0.2)]

    _, _, attach_value = compute_attach_metrics(lines)

    assert attach_value == 0.3


def test_generator_input_is_consumed_once() -> None:
    """The function accepts any iterable, including a one-shot generator."""
    lines = (Line(category, total) for category, total in [("roof", 700.0), ("trim", 100.0)])

    assert compute_attach_metrics(lines) == ("roof", 1, 100.0)
