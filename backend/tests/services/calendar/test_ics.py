"""iCalendar invite rendering.

Wire-format mistakes here fail silently — the client drops the invite and the rep
just never sees the appointment — so the escaping, folding, and UTC conversion
rules are pinned explicitly.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.services.calendar.ics import (
    CRLF,
    MAX_LINE_OCTETS,
    CalendarInvite,
    appointment_uid,
    escape_text,
    fold_line,
    format_utc,
    render_invite,
)


def _invite(**overrides) -> CalendarInvite:
    base = {
        "uid": appointment_uid(42),
        "starts_at": datetime(2026, 6, 10, 18, 0, tzinfo=UTC),
        "duration_minutes": 60,
        "summary": "Pressure washing estimate",
    }
    base.update(overrides)
    return CalendarInvite(**base)


def _unfold(document: str) -> str:
    """Reverse RFC 5545 folding so property values can be asserted whole."""
    return document.replace(f"{CRLF} ", "")


class TestEscaping:
    def test_special_characters_are_escaped(self) -> None:
        assert escape_text("a;b,c\\d") == "a\\;b\\,c\\\\d"

    def test_backslash_is_escaped_before_other_characters(self) -> None:
        # A naive ordering double-escapes the backslashes it just inserted.
        assert escape_text("\\;") == "\\\\\\;"

    def test_newlines_become_literal_backslash_n(self) -> None:
        assert escape_text("line1\nline2") == "line1\\nline2"
        assert escape_text("line1\r\nline2") == "line1\\nline2"


class TestFolding:
    def test_short_line_is_untouched(self) -> None:
        assert fold_line("SUMMARY:hi") == "SUMMARY:hi"

    def test_long_line_is_folded_with_leading_space(self) -> None:
        folded = fold_line("SUMMARY:" + "x" * 200)
        segments = folded.split(CRLF)
        assert len(segments) > 1
        assert all(seg.startswith(" ") for seg in segments[1:])

    def test_no_segment_exceeds_the_octet_limit(self) -> None:
        folded = fold_line("DESCRIPTION:" + "é" * 200)
        for segment in folded.split(CRLF):
            assert len(segment.encode("utf-8")) <= MAX_LINE_OCTETS

    def test_multibyte_characters_are_never_split(self) -> None:
        folded = fold_line("DESCRIPTION:" + "é" * 200)
        # A split code point raises here; round-tripping proves each segment is
        # independently valid UTF-8.
        for segment in folded.split(CRLF):
            segment.encode("utf-8").decode("utf-8")

    def test_folding_is_reversible(self) -> None:
        original = "DESCRIPTION:" + "abcdé" * 40
        assert _unfold(fold_line(original)) == original


class TestFormatUtc:
    def test_utc_value(self) -> None:
        assert format_utc(datetime(2026, 6, 10, 18, 0, tzinfo=UTC)) == "20260610T180000Z"

    def test_local_value_is_converted(self) -> None:
        eastern = datetime(2026, 6, 10, 14, 0, tzinfo=ZoneInfo("America/New_York"))
        assert format_utc(eastern) == "20260610T180000Z"

    def test_naive_value_is_treated_as_utc(self) -> None:
        assert format_utc(datetime(2026, 6, 10, 18, 0)) == "20260610T180000Z"


class TestRenderInvite:
    def test_document_structure(self) -> None:
        doc = render_invite(_invite())
        assert doc.startswith("BEGIN:VCALENDAR")
        assert doc.endswith(f"END:VCALENDAR{CRLF}")
        assert "BEGIN:VEVENT" in doc
        assert "END:VEVENT" in doc

    def test_every_line_is_crlf_terminated(self) -> None:
        doc = render_invite(_invite())
        assert "\n" not in doc.replace(CRLF, "")

    def test_end_time_derives_from_duration(self) -> None:
        doc = render_invite(_invite(duration_minutes=90))
        assert "DTSTART:20260610T180000Z" in doc
        assert "DTEND:20260610T193000Z" in doc

    def test_local_start_is_stored_as_utc(self) -> None:
        eastern = datetime(2026, 6, 10, 14, 0, tzinfo=ZoneInfo("America/New_York"))
        doc = render_invite(_invite(starts_at=eastern, duration_minutes=30))
        assert "DTSTART:20260610T180000Z" in doc
        assert "DTEND:20260610T183000Z" in doc

    def test_uid_is_stable_for_the_same_appointment(self) -> None:
        assert appointment_uid(42) == appointment_uid(42)
        assert appointment_uid(42) != appointment_uid(43)
        assert f"UID:{appointment_uid(42)}" in render_invite(_invite())

    def test_organizer_and_attendee_are_mailto_addresses(self) -> None:
        doc = _unfold(
            render_invite(
                _invite(
                    organizer_email="ops@example.com",
                    organizer_name="Ops Team",
                    attendee_email="rep@example.com",
                    attendee_name="Dana Reyes",
                )
            )
        )
        assert 'ORGANIZER;CN="Ops Team":mailto:ops@example.com' in doc
        assert 'ATTENDEE;CN="Dana Reyes"' in doc
        assert "mailto:rep@example.com" in doc
        assert "RSVP=TRUE" in doc

    def test_person_properties_are_omitted_without_an_email(self) -> None:
        doc = render_invite(_invite())
        assert "ORGANIZER" not in doc
        assert "ATTENDEE" not in doc

    def test_quotes_in_a_display_name_cannot_break_the_parameter(self) -> None:
        doc = _unfold(
            render_invite(_invite(attendee_email="rep@example.com", attendee_name='Da"ve'))
        )
        assert 'CN="Dave"' in doc

    def test_summary_and_description_are_escaped(self) -> None:
        doc = _unfold(
            render_invite(
                _invite(
                    summary="Estimate; roof, gutters",
                    description="Call first\nGate code: 1234",
                )
            )
        )
        assert "SUMMARY:Estimate\\; roof\\, gutters" in doc
        assert "DESCRIPTION:Call first\\nGate code: 1234" in doc

    def test_confirmed_invite_uses_request_method_and_has_an_alarm(self) -> None:
        doc = render_invite(_invite())
        assert "METHOD:REQUEST" in doc
        assert "STATUS:CONFIRMED" in doc
        assert "BEGIN:VALARM" in doc

    def test_cancellation_uses_cancel_method_and_drops_the_alarm(self) -> None:
        doc = render_invite(_invite(cancelled=True, sequence=1))
        assert "METHOD:CANCEL" in doc
        assert "STATUS:CANCELLED" in doc
        assert "SEQUENCE:1" in doc
        assert "BEGIN:VALARM" not in doc

    def test_sequence_defaults_to_zero(self) -> None:
        assert "SEQUENCE:0" in render_invite(_invite())

    def test_dtstamp_is_present(self) -> None:
        doc = render_invite(_invite(), now=datetime(2026, 6, 1, 12, 0, tzinfo=UTC))
        assert "DTSTAMP:20260601T120000Z" in doc

    def test_long_summary_is_folded_but_recoverable(self) -> None:
        summary = "Estimate for " + "a very long service description " * 6
        doc = render_invite(_invite(summary=summary))
        for line in doc.split(CRLF):
            assert len(line.encode("utf-8")) <= MAX_LINE_OCTETS
        assert f"SUMMARY:{summary}" in _unfold(doc)
