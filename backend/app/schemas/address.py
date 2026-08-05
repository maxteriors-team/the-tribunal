"""Schemas for operator-facing address autocomplete.

The field names in :class:`AddressParts` deliberately mirror the ``address_*``
columns on :class:`app.models.contact.Contact`, so the frontend can spread a
resolved address straight onto a contact form without a translation table that
would silently drift.
"""

from typing import Literal

from pydantic import BaseModel, Field

AddressProvider = Literal["google_places", "census", "none"]


class AddressParts(BaseModel):
    """A resolved postal address split into the fields a contact stores."""

    address_line1: str = ""
    address_line2: str = ""
    address_city: str = ""
    address_state: str = ""
    address_zip: str = ""


class AddressSuggestion(BaseModel):
    """One pickable address candidate.

    ``parts`` is populated only by providers that return a structured address
    with the candidate list (the Census geocoder does). When it is ``None`` the
    caller must resolve the suggestion before it can fill a form — that second
    round trip is what Google's session-token billing model expects.
    """

    id: str
    label: str
    description: str = ""
    parts: AddressParts | None = None


class AddressSuggestionsResponse(BaseModel):
    """Candidate list plus the provider that produced it.

    ``provider="none"`` means no lookup provider is available, which the UI
    treats as "leave the plain text field alone" rather than as an error.
    """

    provider: AddressProvider
    suggestions: list[AddressSuggestion] = Field(default_factory=list)


class AddressResolveRequest(BaseModel):
    """Ask for the structured address behind a previously returned suggestion."""

    suggestion_id: str = Field(min_length=1, max_length=512)
    # Ties the resolve back to the keystrokes that preceded it so Google bills
    # one autocomplete session instead of one request per keystroke.
    session_token: str | None = Field(default=None, max_length=128)
