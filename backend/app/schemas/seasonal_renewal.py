"""Schemas for the single-customer holiday-lighting renewal surface.

Read-only projections plus one create. Nothing here is client-settable beyond
*which* customer to renew: the line items, prices and seasonal tags all come from
the prior quote server-side, so a renewal cannot be used to write arbitrary
priced lines onto a quote.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RenewalCandidateResponse(BaseModel):
    """One house lit in an earlier season, with the quote a renewal would copy."""

    model_config = ConfigDict(from_attributes=True)

    contact_id: int
    contact_name: str
    quote_id: uuid.UUID
    quote_number: str
    quote_total: float
    line_item_count: int
    #: When the signup was recorded — the season being renewed *from*.
    signed_up_at: datetime


class RenewalCandidateList(BaseModel):
    """A page of renewal candidates plus the season the operator is selling."""

    items: list[RenewalCandidateResponse] = Field(default_factory=list)
    total: int = 0
    #: Calendar year of the season the renewal quote would be for.
    season_year: int
