"""Attach-rate metrics derived from a quote's line items.

Answers two questions cheaply at report time: *what job was this really?* and
*what rode along with it?* A quote for a roof with a gutter add-on is a roof job
(``primary_service="roof"``) with one attachment worth the gutter total, and the
denormalized triple lands on :class:`~app.models.quote.Quote` so "average job
value" and "attach rate" never need a join + group-by over the line items.

Deliberately pure and I/O-free: no session, no ORM classes, no rounding policy
beyond cents. Callers pass anything with ``service_category`` and ``total`` \u2014
persisted ``QuoteLineItem`` rows, unsaved ones, or plain stubs in tests \u2014 which
is what makes the rule testable without a database.
"""

from collections.abc import Iterable
from decimal import Decimal
from typing import Protocol, runtime_checkable


@runtime_checkable
class HasCategoryAndTotal(Protocol):
    """Structural type of a priced line: a category label and a line total."""

    @property
    def service_category(self) -> str | None: ...

    @property
    def total(self) -> float | Decimal | None: ...


def _normalize_category(raw: str | None) -> str | None:
    """Return a trimmed category, or None when there is nothing to group on.

    Blank and whitespace-only strings are treated exactly like NULL: a line
    nobody classified must not become a phantom ``""`` service category that
    then wins the primary slot or inflates the attach count.
    """
    if raw is None:
        return None
    cleaned = raw.strip()
    return cleaned or None


def _to_float(raw: float | Decimal | None) -> float:
    """Coerce a money value to float, treating NULL as zero.

    Line totals arrive as ``Decimal`` from Postgres ``Numeric`` and as ``float``
    from unsaved objects; both must group identically. A missing total is 0.0
    rather than an error \u2014 metrics are a reporting side effect and must never be
    the reason a quote fails to save.
    """
    if raw is None:
        return 0.0
    return float(raw)


def compute_attach_metrics(
    line_items: Iterable[HasCategoryAndTotal],
) -> tuple[str | None, int, float]:
    """Return ``(primary_service, attach_count, attach_value)`` for a quote.

    Line totals are summed per ``service_category``. The largest sum wins the
    primary slot; ties break by the largest *single* line in the category, then
    alphabetically, so the answer is deterministic no matter what order the
    lines arrive in. ``attach_count`` counts the remaining distinct categories
    (a category with three lines still counts once) and ``attach_value`` sums
    their totals, rounded to cents.

    Lines with no category are ignored for grouping but still tolerated, so a
    half-classified quote reports on the part that is classified instead of
    crashing or guessing. A quote with no lines at all \u2014 or with no categorized
    line \u2014 has nothing to report and yields ``(None, 0, 0.0)``.
    """
    totals: dict[str, float] = {}
    largest_line: dict[str, float] = {}

    for item in line_items:
        category = _normalize_category(item.service_category)
        if category is None:
            continue
        amount = _to_float(item.total)
        totals[category] = totals.get(category, 0.0) + amount
        largest_line[category] = max(largest_line.get(category, amount), amount)

    if not totals:
        return None, 0, 0.0

    # Descending by summed total, then by biggest single line, then A-Z. The
    # first two are negated so one ascending sort expresses all three rules.
    primary = min(totals, key=lambda c: (-totals[c], -largest_line[c], c))

    attached = [category for category in totals if category != primary]
    attach_value = round(sum(totals[category] for category in attached), 2)
    return primary, len(attached), attach_value
