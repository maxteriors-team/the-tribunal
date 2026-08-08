"""iCalendar (RFC 5545) invite generation for appointments.

The CRM ``appointments`` table is the source of truth for scheduling, but nobody
sits in the CRM all day — reps live in Google/Apple/Outlook Calendar. Attaching a
``text/calendar`` VEVENT to the booked-notification email puts the appointment on
the calendar they actually watch, with no per-user OAuth or external calendar
account to maintain.

Two details make the difference between "this works" and "this silently doesn't":

- **Stable UID.** Calendar clients key off ``UID``; re-sending the same UID with a
  higher ``SEQUENCE`` *updates* the existing event instead of creating a duplicate,
  and ``METHOD:CANCEL`` removes it. The UID is derived from the appointment's
  primary key so a reschedule lands on the same event.
- **Wire format.** Lines are CRLF-terminated and folded at 75 **octets** (not
  characters), and text values escape ``\\``, ``;``, ``,`` and newlines. Clients
  reject or mangle files that get this wrong, which shows up as an invite that
  simply never appears.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

# RFC 5545 §3.1: lines are folded so no line exceeds 75 octets, excluding CRLF.
MAX_LINE_OCTETS = 75
CRLF = "\r\n"
PRODID = "-//The Tribunal//Appointment Booking//EN"
# Domain used to namespace generated UIDs. Not resolved — RFC 5545 only requires
# global uniqueness, and appointment IDs are unique per deployment.
UID_DOMAIN = "the-tribunal.app"


def escape_text(value: str) -> str:
    """Escape a value for an iCalendar TEXT property (RFC 5545 §3.3.11).

    Backslash must be escaped first, otherwise the escapes added for ``;`` and
    ``,`` would themselves be re-escaped.
    """
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def fold_line(line: str) -> str:
    """Fold one content line to 75 octets per RFC 5545 §3.1.

    Folding counts UTF-8 octets, and a continuation line starts with a single
    space. Multi-byte characters are never split across a fold boundary — a
    client decoding a split code point would see mojibake or reject the file.
    """
    encoded = line.encode("utf-8")
    if len(encoded) <= MAX_LINE_OCTETS:
        return line

    chunks: list[str] = []
    current = ""
    current_octets = 0
    # Continuation lines carry a leading space, so they fit one octet less.
    limit = MAX_LINE_OCTETS

    for char in line:
        char_octets = len(char.encode("utf-8"))
        if current_octets + char_octets > limit:
            chunks.append(current)
            current = char
            current_octets = char_octets
            limit = MAX_LINE_OCTETS - 1
        else:
            current += char
            current_octets += char_octets

    if current:
        chunks.append(current)

    return CRLF.join([chunks[0], *[f" {chunk}" for chunk in chunks[1:]]])


def format_utc(value: datetime) -> str:
    """Render a datetime as an iCalendar UTC timestamp (``20260610T180000Z``).

    Naive values are assumed UTC, matching what ``timestamptz`` columns return.
    """
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return aware.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def appointment_uid(appointment_id: int | str) -> str:
    """Return the stable iCalendar UID for an appointment."""
    return f"appointment-{appointment_id}@{UID_DOMAIN}"


@dataclass(frozen=True, slots=True)
class CalendarInvite:
    """Everything needed to render one VEVENT."""

    uid: str
    starts_at: datetime
    duration_minutes: int
    summary: str
    description: str = ""
    location: str = ""
    organizer_email: str | None = None
    organizer_name: str | None = None
    attendee_email: str | None = None
    attendee_name: str | None = None
    # Bumped on every update so clients replace rather than ignore the event.
    sequence: int = 0
    cancelled: bool = False

    @property
    def ends_at(self) -> datetime:
        return self.starts_at + timedelta(minutes=self.duration_minutes)

    @property
    def method(self) -> str:
        return "CANCEL" if self.cancelled else "REQUEST"

    @property
    def filename(self) -> str:
        return "invite.ics"


def _person_property(
    prop: str,
    email: str,
    name: str | None,
    extra_params: str = "",
) -> str:
    """Build an ORGANIZER/ATTENDEE property line with an optional display name."""
    params = ""
    if name:
        # CN is a quoted string; strip quotes rather than escape them, since a
        # quoted-string in a parameter value cannot contain a double quote.
        params += f';CN="{name.replace(chr(34), "")}"'
    params += extra_params
    return f"{prop}{params}:mailto:{email}"


def render_invite(invite: CalendarInvite, *, now: datetime | None = None) -> str:
    """Render a complete VCALENDAR document for ``invite``.

    Returns CRLF-delimited text suitable for a ``text/calendar`` attachment.
    """
    stamp = format_utc(now or datetime.now(UTC))

    lines: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        f"METHOD:{invite.method}",
        "BEGIN:VEVENT",
        f"UID:{invite.uid}",
        f"DTSTAMP:{stamp}",
        f"DTSTART:{format_utc(invite.starts_at)}",
        f"DTEND:{format_utc(invite.ends_at)}",
        f"SEQUENCE:{invite.sequence}",
        f"SUMMARY:{escape_text(invite.summary)}",
        f"STATUS:{'CANCELLED' if invite.cancelled else 'CONFIRMED'}",
    ]

    if invite.description:
        lines.append(f"DESCRIPTION:{escape_text(invite.description)}")
    if invite.location:
        lines.append(f"LOCATION:{escape_text(invite.location)}")
    if invite.organizer_email:
        lines.append(_person_property("ORGANIZER", invite.organizer_email, invite.organizer_name))
    if invite.attendee_email:
        lines.append(
            _person_property(
                "ATTENDEE",
                invite.attendee_email,
                invite.attendee_name,
                extra_params=";ROLE=REQ-PARTICIPANT;PARTSTAT=NEEDS-ACTION;RSVP=TRUE",
            )
        )

    if not invite.cancelled:
        # A 1-hour-ahead popup: the whole point of the invite is that the rep is
        # reminded by their own calendar, not only by our reminder worker.
        lines.extend(
            [
                "BEGIN:VALARM",
                "ACTION:DISPLAY",
                f"DESCRIPTION:{escape_text(invite.summary)}",
                "TRIGGER:-PT1H",
                "END:VALARM",
            ]
        )

    lines.extend(["END:VEVENT", "END:VCALENDAR"])

    return CRLF.join(fold_line(line) for line in lines) + CRLF
