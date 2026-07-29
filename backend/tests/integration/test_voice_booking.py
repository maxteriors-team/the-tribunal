#!/usr/bin/env python3
"""Voice agent booking tests.

Exercises the voice agent's tool calling and date handling WITHOUT making
actual phone calls: the booking tests drive the very tool callback that a live
call hands to the model, so a refactor of the dispatch path breaks them.

Requires a local Postgres (``make dev.db`` + ``make migrate``). Availability and
booking are answered from the workspace's business hours minus its CRM
appointments (``BookingService``) — there is no external calendar in this path.

Usage:
    cd backend
    # As pytest (integration marker required, opt-in):
    uv run pytest -m integration tests/integration/test_voice_booking.py
    # Or as a standalone script:
    uv run python tests/integration/test_voice_booking.py

Tests:
    1. Date format parsing (what Grok sends vs what we expect)
    2. Time format parsing
    3. Date context injection (what the agent sees)
    4. Voice tool dispatch: check_availability / book_appointment through
       ``create_tool_callback``, plus the HITL approval gate they pass through
    5. Grok session configuration
    6. Cal.com API (legacy direct client)
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete, select

# Add backend/ — NOT backend/tests/ — to the path so ``import app...`` works when
# this file runs as a standalone script. Pointing one level too shallow puts
# tests/ on sys.path, where tests/websockets/ shadows the real ``websockets``
# dependency and breaks every module importing it.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.core.config import settings
from app.db.session import AsyncSessionLocal, engine
from app.models.agent import Agent
from app.models.human_profile import HumanProfile
from app.models.pending_action import PendingAction
from app.models.user import User
from app.models.workspace import Workspace
from app.services.ai.tool_executor import create_tool_callback
from app.services.approval.approval_gate_service import approval_gate_service
from app.services.calendar.calcom import CalComService

pytestmark = pytest.mark.integration


# ANSI colors for output
class Colors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    BOLD = "\033[1m"
    END = "\033[0m"


def log_pass(msg: str) -> None:
    print(f"{Colors.GREEN}[PASS]{Colors.END} {msg}")


def log_fail(msg: str) -> None:
    print(f"{Colors.RED}[FAIL]{Colors.END} {msg}")


def log_info(msg: str) -> None:
    print(f"{Colors.BLUE}[INFO]{Colors.END} {msg}")


def log_warn(msg: str) -> None:
    print(f"{Colors.YELLOW}[WARN]{Colors.END} {msg}")


def log_section(msg: str) -> None:
    print(f"\n{Colors.BOLD}{'=' * 60}{Colors.END}")
    print(f"{Colors.BOLD}{msg}{Colors.END}")
    print(f"{Colors.BOLD}{'=' * 60}{Colors.END}\n")


# ============================================================
# Test 1: Date Format Parsing
# ============================================================


def test_date_parsing() -> dict[str, bool]:
    """Test various date formats that Grok might output.

    The voice_bridge expects YYYY-MM-DD format. This tests what happens
    with other formats Grok might output.
    """
    log_section("TEST 1: Date Format Parsing")

    timezone = "America/New_York"
    try:
        tz = ZoneInfo(timezone)
    except Exception:
        tz = ZoneInfo("UTC")

    now = datetime.now(tz)
    tomorrow = now + timedelta(days=1)

    # Test cases: (input_format, should_pass, description)
    test_cases = [
        # Expected format (should pass)
        (tomorrow.strftime("%Y-%m-%d"), True, "YYYY-MM-DD (expected format)"),
        ("2026-01-27", True, "YYYY-MM-DD explicit"),
        # Common Grok outputs (likely to fail)
        ("tomorrow", False, "Natural language: tomorrow"),
        ("next Monday", False, "Natural language: next Monday"),
        ("January 27, 2026", False, "Long date format"),
        ("01/27/2026", False, "US date format MM/DD/YYYY"),
        ("27/01/2026", False, "EU date format DD/MM/YYYY"),
        ("Jan 27", False, "Short month format"),
        ("Monday", False, "Day name only"),
        ("next week", False, "Relative: next week"),
        # Edge cases
        ("2026-1-27", False, "Missing leading zeros"),
        ("2026/01/27", False, "Wrong separator"),
    ]

    results: dict[str, bool] = {}

    for date_input, expected_pass, description in test_cases:
        try:
            datetime.strptime(date_input, "%Y-%m-%d")
            passed = True
        except ValueError:
            passed = False

        actual_match = passed == expected_pass
        results[date_input] = actual_match

        if passed and expected_pass:
            log_pass(f"{description}: '{date_input}' -> parsed correctly")
        elif not passed and not expected_pass:
            log_pass(f"{description}: '{date_input}' -> correctly rejected (expected)")
        elif passed and not expected_pass:
            log_warn(f"{description}: '{date_input}' -> parsed but shouldn't have")
        else:
            log_fail(f"{description}: '{date_input}' -> failed to parse but should have")

    return results


# ============================================================
# Test 2: Time Format Parsing
# ============================================================


def test_time_parsing() -> dict[str, bool]:
    """Test various time formats that Grok might output."""
    log_section("TEST 2: Time Format Parsing")

    # Test cases: (input_format, should_pass, description)
    test_cases = [
        # Expected format (should pass)
        ("14:00", True, "HH:MM 24-hour (expected)"),
        ("09:30", True, "HH:MM with leading zero"),
        # Common Grok outputs (likely to fail)
        ("2:00 PM", False, "12-hour with AM/PM"),
        ("2pm", False, "Short 12-hour format"),
        ("14:00:00", False, "HH:MM:SS with seconds"),
        ("2 o'clock", False, "Natural language"),
        ("afternoon", False, "Vague time"),
        ("9:30", False, "Missing leading zero (depends)"),
    ]

    results: dict[str, bool] = {}

    for time_input, expected_pass, description in test_cases:
        try:
            # The voice_bridge parses as part of datetime
            datetime.strptime(f"2026-01-27 {time_input}", "%Y-%m-%d %H:%M")
            passed = True
        except ValueError:
            passed = False

        actual_match = passed == expected_pass
        results[time_input] = actual_match

        if passed and expected_pass:
            log_pass(f"{description}: '{time_input}' -> parsed correctly")
        elif not passed and not expected_pass:
            log_pass(f"{description}: '{time_input}' -> correctly rejected")
        elif passed and not expected_pass:
            log_warn(f"{description}: '{time_input}' -> parsed unexpectedly")
        else:
            log_fail(f"{description}: '{time_input}' -> failed to parse")

    return results


# ============================================================
# Test 3: Date Context Generation
# ============================================================


def test_date_context() -> None:
    """Test the date context that gets injected into Grok's prompt."""
    log_section("TEST 3: Date Context Generation")

    timezone = "America/New_York"
    try:
        tz = ZoneInfo(timezone)
    except Exception:
        tz = ZoneInfo("UTC")

    now = datetime.now(tz)

    # This is the exact format used in grok_voice_agent.py:239
    current_time = now.strftime("%A, %B %d, %Y at %I:%M %p")
    date_context = f"The current date and time is {current_time}.\n\n"

    log_info(f"Timezone: {timezone}")
    log_info(f"Current datetime: {now}")
    log_info("Date context sent to Grok:")
    print(f"  '{date_context.strip()}'")

    # Check if the format is clear enough for Grok
    log_info("\nAnalysis:")
    if "2026" in date_context:
        log_pass("Year is included (2026)")
    else:
        log_fail("Year is missing - Grok may use wrong year!")

    if now.strftime("%B") in date_context:
        log_pass(f"Month is included ({now.strftime('%B')})")
    else:
        log_fail("Month name missing")

    if now.strftime("%A") in date_context:
        log_pass(f"Day of week included ({now.strftime('%A')})")
    else:
        log_warn("Day of week missing - helps Grok understand 'next Monday'")


# ============================================================
# Test 4: Voice Tool Dispatch (the live tool-callback path)
# ============================================================

TEST_TIMEZONE = "America/New_York"

# Open every weekday AND weekend 9-5 so availability is deterministic no matter
# which day the suite runs on: any future date has slots.
_BUSINESS_HOURS: dict[str, Any] = {
    "is_24_7": False,
    "schedule": {
        day: {"enabled": True, "open": "09:00", "close": "17:00"}
        for day in (
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
        )
    },
}


class _CallLog:
    """structlog-shaped logger the tool callback writes call events to."""

    def info(self, msg: str, **kwargs: Any) -> None:
        pass

    def warning(self, msg: str, **kwargs: Any) -> None:
        log_warn(f"{msg}: {kwargs}")

    def exception(self, msg: str, **kwargs: Any) -> None:
        log_fail(f"{msg}: {kwargs}")


def _tomorrow() -> str:
    """Tomorrow in the agent's timezone, in the YYYY-MM-DD format tools expect."""
    return (datetime.now(ZoneInfo(TEST_TIMEZONE)) + timedelta(days=1)).strftime("%Y-%m-%d")


@asynccontextmanager
async def _booking_agent() -> AsyncIterator[tuple[uuid.UUID, Agent]]:
    """Seed a workspace + booking agent, yield them, then delete the workspace.

    The engine pool is disposed around the body because pytest-asyncio gives
    each test a fresh event loop, and a pooled asyncpg connection bound to a
    closed loop surfaces later as ``Event loop is closed``.
    """
    await engine.dispose()
    async with AsyncSessionLocal() as db:
        workspace = Workspace(
            id=uuid.uuid4(),
            name="Voice Booking Test Co",
            slug=f"voice-booking-{uuid.uuid4().hex[:8]}",
            settings={"business_hours": _BUSINESS_HOURS},
        )
        db.add(workspace)
        await db.flush()
        agent = Agent(
            workspace_id=workspace.id,
            name="Jess",
            system_prompt="You are Jess, a friendly appointment booking assistant.",
            enabled_tools=["check_availability", "book_appointment"],
        )
        db.add(agent)
        await db.commit()
        await db.refresh(agent)
        workspace_id = workspace.id

    try:
        yield workspace_id, agent
    finally:
        # Workspace FKs cascade to the agent, human profile, and pending
        # actions, so this leaves no test residue.
        async with AsyncSessionLocal() as db:
            await db.execute(delete(Workspace).where(Workspace.id == workspace_id))
            await db.commit()
        await engine.dispose()


def _voice_tool_callback(agent: Agent, workspace_id: uuid.UUID) -> Any:
    """Build the tool callback exactly as ``voice_bridge`` does for a live call.

    See ``_setup_voice_session`` in ``app/websockets/voice_bridge.py``: it calls
    ``create_tool_callback(...)`` and hands the result to the voice session,
    which invokes it as ``callback(call_id, function_name, arguments)`` for
    every tool call the model emits.

    ``call_control_id`` is None here — there is no Telnyx leg — so the callback
    exercises the tool contract the model sees without the call-scoped
    Appointment/Message persistence that a real leg triggers.
    """
    return create_tool_callback(
        agent=agent,
        contact_info={
            "name": "Test User",
            "phone": "+15551234567",
            "email": "test@example.com",
        },
        timezone=TEST_TIMEZONE,
        call_control_id=None,
        log=_CallLog(),
        workspace_id=workspace_id,
    )


async def test_simulated_tool_calls() -> None:
    """Simulate the tool calls Grok makes, through the real dispatch path.

    Drives ``create_tool_callback`` -> approval gate -> ``VoiceToolExecutor``
    -> ``BookingService``, which is what runs on a live call today.
    """
    log_section("TEST 4: Voice Tool Dispatch")

    async with _booking_agent() as (workspace_id, agent):
        callback = _voice_tool_callback(agent, workspace_id)
        date_str = _tomorrow()

        # 4a. check_availability in the documented YYYY-MM-DD format.
        log_info("4a. Testing check_availability with YYYY-MM-DD format...")
        availability = await callback("call-test-1", "check_availability", {"start_date": date_str})

        assert availability["success"] is True, availability
        assert availability["available"] is True, availability
        slots = availability["slots"]
        assert slots, "expected open slots inside 9-5 business hours"
        assert all(slot["date"] == date_str for slot in slots), slots
        # Voice slots carry a speakable 12-hour time; the day opens at 9.
        assert slots[0]["time"] == "09:00", slots[0]
        assert slots[0]["display_time"] == "9:00 AM", slots[0]
        # Anti-hallucination guardrail the model is handed with the slots.
        assert "Do NOT make up" in availability["message"], availability
        log_pass(f"check_availability returned {len(slots)} slots for {date_str}")

        # 4b. The format Grok gets wrong is rejected, never silently mis-booked.
        log_info("4b. Testing check_availability with 'tomorrow' (wrong format)...")
        bad_format = await callback("call-test-1", "check_availability", {"start_date": "tomorrow"})

        assert bad_format["success"] is False, bad_format
        assert "Invalid date format" in bad_format["error"], bad_format
        log_pass("check_availability rejected natural-language 'tomorrow'")

        # 4c. book_appointment against a slot the tool just offered.
        log_info("4c. Testing book_appointment with a slot from check_availability...")
        booked = await callback(
            "call-test-1",
            "book_appointment",
            {
                "date": date_str,
                "time": slots[0]["time"],
                "email": "test-voice-booking@example.com",
                "duration_minutes": 30,
                "notes": "Test booking from the voice tool integration test",
            },
        )

        assert booked["success"] is True, booked
        assert slots[0]["display_time"] in booked["message"], booked
        assert "test-voice-booking@example.com" in booked["message"], booked
        log_pass(f"book_appointment confirmed {date_str} at {slots[0]['display_time']}")

        # 4d. Missing email is refused with a repairable instruction to the model.
        log_info("4d. Testing book_appointment without an email...")
        no_email = await callback(
            "call-test-1",
            "book_appointment",
            {"date": date_str, "time": slots[0]["time"]},
        )

        assert no_email["success"] is False, no_email
        assert "Email address is required" in no_email["error"], no_email
        log_pass("book_appointment asked for the missing email instead of failing")

        # 4e. A hallucinated tool name falls through the dispatch table safely.
        unknown = await callback("call-test-1", "reschedule_everything", {})

        assert unknown["success"] is False, unknown
        assert "Unknown function" in unknown["error"], unknown
        log_pass("unknown tool name rejected without raising")


async def test_booking_tool_call_waits_for_operator_approval() -> None:
    """A gated booking is queued for the operator, then executes on approval.

    Every state-changing voice tool goes through ``approval_gate_service``.
    Under an "ask" policy the model is told the action is pending, and
    approving the queued action later runs it through the booking executor that
    ``ApprovalGateService._execute_book_appointment`` delegates to.
    """
    log_section("TEST 4b: Voice Booking Approval Gate")

    async with _booking_agent() as (workspace_id, agent):
        async with AsyncSessionLocal() as db:
            db.add(
                HumanProfile(
                    workspace_id=workspace_id,
                    agent_id=agent.id,
                    display_name="Test Operator",
                    action_policies={"book_appointment": "ask"},
                    default_policy="auto",
                )
            )
            operator = User(
                email=f"operator-{uuid.uuid4().hex[:8]}@example.com",
                hashed_password="$argon2id$v=19$m=65536,t=3,p=4$placeholderfortests",
                full_name="Test Operator",
            )
            db.add(operator)
            await db.commit()
            operator_id = operator.id

        callback = _voice_tool_callback(agent, workspace_id)
        date_str = _tomorrow()

        try:
            gated = await callback(
                "call-test-2",
                "book_appointment",
                {
                    "date": date_str,
                    "time": "09:00",
                    "email": "test-voice-booking@example.com",
                    "duration_minutes": 30,
                },
            )

            # The model is told to stall, not that the booking succeeded.
            assert gated["success"] is False, gated
            assert gated["pending_approval"] is True, gated
            log_pass("book_appointment queued for operator approval")

            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(PendingAction).where(PendingAction.workspace_id == workspace_id)
                )
                action = result.scalar_one()

                assert action.action_type == "book_appointment", action
                assert action.status == "pending", action
                assert action.action_payload["date"] == date_str, action.action_payload
                assert action.context["source"] == "voice_call", action.context

                # Operator approves in the dashboard, then the gate executes it.
                await approval_gate_service.approve_action(db, action.id, operator_id)
                execution = await approval_gate_service.execute_approved_action(db, action)

                assert execution["status"] == "booked", execution
                assert action.status == "executed", action
            log_pass("approved action executed through the booking executor")
        finally:
            async with AsyncSessionLocal() as db:
                await db.execute(delete(User).where(User.id == operator_id))
                await db.commit()


# ============================================================
# Test 5: Full Grok Session Simulation
# ============================================================


async def test_grok_session_config() -> None:
    """Test the Grok session configuration and date context injection."""
    log_section("TEST 5: Grok Session Configuration")

    from app.services.ai.grok import GrokVoiceAgentSession

    # Check if API key is available
    if not settings.xai_api_key:
        log_warn("XAI_API_KEY not set - skipping Grok session test")
        return

    # Create a mock agent
    class MockAgent:
        def __init__(self):
            self.id = "test-agent-123"
            self.name = "Jess"
            self.system_prompt = "You are Jess, a friendly appointment booking assistant."
            self.voice_id = "eve"
            self.turn_detection_mode = "server_vad"
            self.enabled_tools = ["book_appointment", "check_availability"]
            self.calcom_event_type_id = 12345
            self.initial_greeting = "Hi there! How can I help you today?"

    agent = MockAgent()

    # Create session (don't actually connect)
    session = GrokVoiceAgentSession(
        api_key=settings.xai_api_key,
        agent=agent,  # type: ignore
        enable_tools=True,
        timezone="America/New_York",
    )

    # Test date context generation
    date_context = session._get_date_context()

    log_info("Generated date context:")
    print(f"  '{date_context.strip()}'")

    # Verify the date context
    now = datetime.now(ZoneInfo("America/New_York"))

    if str(now.year) in date_context:
        log_pass(f"Year {now.year} is in date context")
    else:
        log_fail(f"Year {now.year} MISSING from date context!")

    if now.strftime("%B") in date_context:
        log_pass(f"Month {now.strftime('%B')} is in date context")
    else:
        log_fail("Month MISSING from date context!")

    if now.strftime("%A") in date_context:
        log_pass(f"Day {now.strftime('%A')} is in date context")
    else:
        log_warn("Day of week missing from date context")


# ============================================================
# Test 6: Cal.com API Direct Test
# ============================================================


async def test_calcom_api() -> None:
    """Test Cal.com API directly (not through voice agent)."""
    log_section("TEST 6: Cal.com API Direct Test")

    event_type_id = int(os.getenv("TEST_CALCOM_EVENT_TYPE_ID", "0"))

    if not event_type_id:
        log_warn("TEST_CALCOM_EVENT_TYPE_ID not set - skipping")
        log_info("Set this in your .env to test Cal.com availability")
        return

    if not settings.calcom_api_key:
        log_warn("CALCOM_API_KEY not set - skipping")
        return

    calcom = CalComService(settings.calcom_api_key)

    try:
        timezone = "America/New_York"
        tz = ZoneInfo(timezone)
        now = datetime.now(tz)

        # Check availability for next 3 days
        start_date = now + timedelta(days=1)
        end_date = now + timedelta(days=3)

        log_info(f"Checking availability from {start_date.date()} to {end_date.date()}")

        slots = await calcom.get_availability(
            event_type_id=event_type_id,
            start_date=start_date,
            end_date=end_date,
            timezone=timezone,
        )

        log_pass(f"Cal.com API call succeeded - {len(slots)} slots available")

        if slots:
            log_info("Sample available slots:")
            for slot in slots[:5]:
                log_info(f"  - {slot.get('date')} at {slot.get('time')}")
        else:
            log_warn("No slots available in the next 3 days")

    except Exception as e:
        log_fail(f"Cal.com API call failed: {e}")

    finally:
        await calcom.close()


# ============================================================
# Main
# ============================================================


async def main() -> None:
    """Run all voice booking tests."""
    print(f"\n{Colors.BOLD}{'=' * 60}{Colors.END}")
    print(f"{Colors.BOLD}GROK VOICE AGENT BOOKING TEST SUITE{Colors.END}")
    print(f"{Colors.BOLD}{'=' * 60}{Colors.END}")
    print(f"\nRunning at: {datetime.now()}")
    print(f"Environment: {os.getenv('ENVIRONMENT', 'development')}")

    # Track overall results
    all_passed = True

    # Test 1: Date parsing
    date_results = test_date_parsing()
    if not all(date_results.values()):
        all_passed = False

    # Test 2: Time parsing
    time_results = test_time_parsing()
    if not all(time_results.values()):
        all_passed = False

    # Test 3: Date context
    test_date_context()

    # Test 4: Voice tool dispatch (asserts; raises on failure)
    await test_simulated_tool_calls()
    await test_booking_tool_call_waits_for_operator_approval()

    # Test 5: Grok session config
    await test_grok_session_config()

    # Test 6: Cal.com API
    await test_calcom_api()

    # Summary
    log_section("TEST SUMMARY")

    if all_passed:
        log_pass("All tests passed!")
    else:
        log_fail("Some tests failed - review output above")

    print("\n" + "=" * 60)
    print("KEY FINDINGS:")
    print("=" * 60)
    print("""
1. Voice tools expect YYYY-MM-DD dates and HH:MM 24-hour times from the model
2. If Grok outputs 'tomorrow' or 'next Monday', the tool rejects it (no booking)
3. The date context IS being injected, but Grok may ignore it
4. Availability/booking are local: workspace business hours minus CRM
   appointments. No external calendar is called on this path.
5. Every state-changing tool call passes the HITL approval gate first

RECOMMENDED FIXES:
1. Add a date parser that handles natural language before the tool call
2. Or: Update tool descriptions to be VERY explicit about format
""")


if __name__ == "__main__":
    asyncio.run(main())
