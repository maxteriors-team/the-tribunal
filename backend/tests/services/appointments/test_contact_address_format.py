"""Contact address rendering for calendar invites.

The address becomes the invite's ``LOCATION``, which is what a rep taps to
navigate — so partial addresses must degrade gracefully rather than render
stray punctuation.
"""

from __future__ import annotations

from app.models.contact import Contact
from app.services.appointments.booking_finalizer import format_contact_address


def test_full_address() -> None:
    contact = Contact(
        address_line1="123 Main St",
        address_line2="Apt 4",
        address_city="Austin",
        address_state="TX",
        address_zip="78701",
    )
    assert format_contact_address(contact) == "123 Main St Apt 4, Austin, TX 78701"


def test_street_only() -> None:
    assert format_contact_address(Contact(address_line1="123 Main St")) == "123 Main St"


def test_partial_address_omits_missing_parts() -> None:
    contact = Contact(address_city="Austin", address_state="TX")
    assert format_contact_address(contact) == "Austin, TX"


def test_zip_only() -> None:
    assert format_contact_address(Contact(address_zip="78701")) == "78701"


def test_no_address_is_empty() -> None:
    assert format_contact_address(Contact()) == ""
