"""Pre-confirmation validation for AI-booked appointments.

An AI agent confirms a booking to the customer in the same breath it calls the
tool. That makes the tool call the last honest moment: anything not checked
*before* it returns success becomes a confirmation the customer believes and the
calendar contradicts — a slot in the past, a malformed email that silently drops
the invite, a five-hour "30 minute" job.

Every booking channel (voice, text, HITL approval) funnels through
``BaseToolExecutor``, so this module is called from there rather than per
channel: a check a channel can skip is a check that will be skipped.

Failures are returned, never raised, and shaped so the model can read them and
re-ask the customer instead of inventing a confirmation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

# Deliberately permissive: this rejects the shapes that certainly cannot receive
# mail (no ``@``, no dot in the domain, whitespace) without pretending to
# implement RFC 5322, which no practical regex does.
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")

MIN_DURATION_MINUTES = 5
MAX_DURATION_MINUTES = 480

# Service types performed at the customer's property. Without an address the rep
# is dispatched to nowhere, so the address is part of a valid booking for these.
ON_SITE_SERVICE_KEYWORDS: tuple[str, ...] = (
    "estimate",
    "quote",
    "inspection",
    "walkthrough",
    "on-site",
    "onsite",
    "in-person",
    "service",
    "cleaning",
    "washing",
    "install",
)


@dataclass(frozen=True, slots=True)
class BookingValidation:
    """Outcome of validating a booking request.

    ``error`` is a short machine-ish code; ``message`` is the sentence the agent
    should act on when re-asking the customer.
    """

    valid: bool
    error: str | None = None
    message: str | None = None
    scheduled_at: datetime | None = None

    def as_tool_result(self) -> dict[str, Any]:
        """Render the failure in the shape every channel's tool result uses."""
        return {
            "success": False,
            "error": self.error or "Invalid booking request",
            "message": self.message or self.error or "Invalid booking request",
            "alternative_slots": [],
        }


def is_valid_email(email: str | None) -> bool:
    """Return True when ``email`` is shaped like a deliverable address."""
    if not email:
        return False
    return bool(_EMAIL_PATTERN.match(email.strip()))


def is_on_site_service(service_type: str | None) -> bool:
    """Return True when this service type happens at the customer's address."""
    if not service_type:
        return False
    lowered = service_type.lower()
    return any(keyword in lowered for keyword in ON_SITE_SERVICE_KEYWORDS)


def parse_scheduled_at(date_str: str, time_str: str, tz: ZoneInfo) -> datetime | None:
    """Combine the model's wall-clock date/time into an aware datetime.

    The strings are wall-clock in the zone the slots were *offered* in, so the
    zone is attached here rather than assumed UTC — stamping UTC shifts every
    booking by the offset.
    """
    try:
        naive = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")  # noqa: DTZ007
    except (ValueError, TypeError):
        return None
    return naive.replace(tzinfo=tz)


def validate_booking_request(
    *,
    date_str: str,
    time_str: str,
    email: str | None,
    duration_minutes: Any,
    tz: ZoneInfo,
    service_type: str | None = None,
    contact_address: str | None = None,
    require_service_type: bool = False,
    now: datetime | None = None,
) -> BookingValidation:
    """Validate a booking request before anything is confirmed to the customer.

    Checks, in the order a failure is most likely: address syntax, parseable and
    future datetime, sane duration, and the service type plus (for on-site work)
    an address to drive to. ``now`` is injectable so tests are deterministic.
    """
    if not is_valid_email(email):
        return BookingValidation(
            valid=False,
            error="invalid_email",
            message=(
                "That email address doesn't look valid. Please ask the customer to "
                "confirm their email before booking."
            ),
        )

    scheduled_at = parse_scheduled_at(date_str, time_str, tz)
    if scheduled_at is None:
        return BookingValidation(
            valid=False,
            error="invalid_datetime",
            message=(
                "That date/time isn't valid. Use YYYY-MM-DD for the date and "
                "24-hour HH:MM for the time."
            ),
        )

    reference = now or datetime.now(tz)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=tz)

    failure = (
        _validate_not_past(scheduled_at, reference)
        or _validate_duration(duration_minutes)
        or _validate_service(service_type, contact_address, require_service_type)
    )
    if failure is not None:
        return failure

    return BookingValidation(valid=True, scheduled_at=scheduled_at)


def _validate_not_past(scheduled_at: datetime, reference: datetime) -> BookingValidation | None:
    """Return a failure when the requested slot has already gone by."""
    if scheduled_at > reference:
        return None
    return BookingValidation(
        valid=False,
        error="datetime_in_past",
        message=(
            "That time is already in the past. Check availability again and "
            "offer the customer an upcoming slot."
        ),
    )


def _validate_service(
    service_type: str | None,
    contact_address: str | None,
    require_service_type: bool,
) -> BookingValidation | None:
    """Return a failure when the service (or the address it needs) is missing."""
    if require_service_type and not (service_type or "").strip():
        return BookingValidation(
            valid=False,
            error="missing_service_type",
            message="Ask the customer what service they need before booking.",
        )

    if is_on_site_service(service_type) and not (contact_address or "").strip():
        return BookingValidation(
            valid=False,
            error="missing_address",
            message=(
                "This visit happens at the customer's property but we have no "
                "address on file. Ask for their service address before booking."
            ),
        )
    return None


def _validate_duration(duration_minutes: Any) -> BookingValidation | None:
    """Return a failure when the duration is not a usable number of minutes."""
    try:
        duration = int(duration_minutes)
    except (TypeError, ValueError):
        return BookingValidation(
            valid=False,
            error="invalid_duration",
            message="The appointment duration must be a whole number of minutes.",
        )

    if duration < MIN_DURATION_MINUTES or duration > MAX_DURATION_MINUTES:
        return BookingValidation(
            valid=False,
            error="invalid_duration",
            message=(
                f"The appointment duration must be between {MIN_DURATION_MINUTES} "
                f"and {MAX_DURATION_MINUTES} minutes."
            ),
        )
    return None
