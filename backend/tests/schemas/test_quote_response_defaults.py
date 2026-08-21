"""Serializing a not-yet-flushed ``Quote`` must not 500.

``QuoteResponse`` is built from ORM objects that have sometimes never been
inserted (the approve path serializes the in-memory quote it just mutated).
SQLAlchemy column/server defaults only land on flush, so those objects read
``None`` for NOT NULL defaulted columns like ``view_count``,
``attach_dismissals``, and ``selected_permanent_kits``. A pydantic field
default does not cover that: it applies when an attribute is *missing*, not
when it is present and null.

This pins the coercion so the next defaulted column added to ``quotes`` fails
here rather than as a 500 on a customer-facing response.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.models.quote import Quote
from app.schemas.quote import QuoteResponse


def _unflushed_quote() -> Quote:
    """A ``Quote`` built in memory exactly as the service does, never inserted."""
    now = datetime.now(UTC)
    return Quote(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        number="QUO-000042",
        status="sent",
        subtotal=5200,
        tax_amount=0,
        discount_amount=0,
        total=5200,
        currency="USD",
        created_at=now,
        updated_at=now,
    )


def test_unflushed_quote_serializes_with_zeroed_defaults() -> None:
    response = QuoteResponse.model_validate(_unflushed_quote())

    # Never opened, nothing attached -- the truthful reading of "no row yet".
    assert response.view_count == 0
    assert response.first_viewed_at is None
    assert response.last_viewed_at is None
    assert response.attach_count == 0
    assert response.attach_value == 0.0
    assert response.attach_dismissals == []
    assert response.selected_permanent_kits == []


def test_real_view_counts_survive_the_coercion() -> None:
    quote = _unflushed_quote()
    opened_at = datetime.now(UTC)
    quote.first_viewed_at = opened_at
    quote.last_viewed_at = opened_at
    quote.view_count = 3

    response = QuoteResponse.model_validate(quote)

    assert response.view_count == 3
    assert response.first_viewed_at == opened_at
    assert response.last_viewed_at == opened_at
