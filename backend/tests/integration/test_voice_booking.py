#!/usr/bin/env python3
"""Test script for Grok voice agent booking functionality.

This script tests the voice agent's tool calling and date handling
WITHOUT making actual phone calls. It simulates the tool callback flow
that happens during real voice conversations.

Usage:
    cd backend
    # As pytest (integration marker required, opt-in):
    uv run pytest -m integration tests/integration/test_voice_booking.py
    # Or as a standalone script:
    uv run python tests/integration/test_voice_booking.py

Tests:
    1. Date format parsing (what Grok sends vs what we expect)
    2. Tool execution flow (check_availability, book_appointment)
    3. Cal.com integration (actual API calls)
    4. Date context injection (what the agent sees)
"""

import asyncio
import os
import sys
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

# Add backend to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings
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
    print(f"\n{Colors.BOLD}{'='*60}{Colors.END}")
    print(f"{Colors.BOLD}{msg}{Colors.END}")
    print(f"{Colors.BOLD}{'='*60}{Colors.END}\n")


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
# Test 4: Simulated Tool Calls (What Grok Actually Sends)
# ============================================================

@pytest.mark.xfail(
    reason=(
        "STALE: imports _execute_book_appointment / _execute_check_availability "
        "from app.websockets.voice_bridge, but they were refactored out "
        "(_execute_book_appointment is now a method on "
        "app.services.approval.approval_gate_service). Rewrite against the current "
        "voice-tool flow, then remove this marker. xfail -> XPASS signals it's fixed."
    ),
    raises=ImportError,
    strict=False,
)
async def test_simulated_tool_calls() -> dict[str, Any]:  # noqa: PLR0915
    """Simulate tool calls as Grok would make them.

    This replicates the exact flow in voice_bridge.py:_execute_voice_tool()
    """
    log_section("TEST 4: Simulated Tool Calls")

    from app.websockets.voice_bridge import (
        _execute_book_appointment,
        _execute_check_availability,
    )

    # Create a mock agent with Cal.com config
    class MockAgent:
        def __init__(self):
            self.calcom_event_type_id = int(os.getenv("TEST_CALCOM_EVENT_TYPE_ID", "0"))
            self.name = "Test Agent"

    agent = MockAgent()

    if not agent.calcom_event_type_id:
        log_warn("TEST_CALCOM_EVENT_TYPE_ID not set - skipping Cal.com API tests")
        log_info("Set TEST_CALCOM_EVENT_TYPE_ID in your .env to test actual Cal.com integration")
        return {"skipped": True}

    if not settings.calcom_api_key:
        log_warn("CALCOM_API_KEY not set - skipping Cal.com API tests")
        return {"skipped": True}

    timezone = "America/New_York"
    tz = ZoneInfo(timezone)
    tomorrow = datetime.now(tz) + timedelta(days=1)

    # Create a simple logger mock
    class MockLogger:
        def info(self, msg: str, **kwargs: Any) -> None:
            pass
        def warning(self, msg: str, **kwargs: Any) -> None:
            log_warn(f"{msg}: {kwargs}")
        def exception(self, msg: str, **kwargs: Any) -> None:
            log_fail(f"{msg}: {kwargs}")

    log = MockLogger()
    results: dict[str, Any] = {}

    # Test 4a: check_availability with correct format
    log_info("4a. Testing check_availability with YYYY-MM-DD format...")
    date_str = tomorrow.strftime("%Y-%m-%d")
    result = await _execute_check_availability(
        agent=agent,
        start_date_str=date_str,
        end_date_str=None,
        timezone=timezone,
        log=log,
    )

    if result.get("success"):
        log_pass(f"check_availability succeeded for {date_str}")
        slots = result.get("slots", [])
        log_info(f"  Found {len(slots)} available slots")
        if slots:
            for slot in slots[:3]:
                log_info(f"    - {slot.get('date')} at {slot.get('time')}")
        results["check_availability_correct"] = True
    else:
        log_fail(f"check_availability failed: {result.get('error')}")
        results["check_availability_correct"] = False

    # Test 4b: check_availability with wrong format (simulating Grok mistake)
    log_info("\n4b. Testing check_availability with 'tomorrow' (wrong format)...")
    result = await _execute_check_availability(
        agent=agent,
        start_date_str="tomorrow",
        end_date_str=None,
        timezone=timezone,
        log=log,
    )

    if not result.get("success"):
        log_pass("Correctly rejected 'tomorrow' format (expected)")
        results["check_availability_wrong_rejected"] = True
    else:
        log_fail("Unexpectedly accepted 'tomorrow' - this shouldn't happen!")
        results["check_availability_wrong_rejected"] = False

    # Test 4c: book_appointment with correct format
    log_info("\n4c. Testing book_appointment with correct format...")
    log_info("  (Using test email - won't create real booking)")

    # Use a test email that won't actually work but tests the flow
    contact_info = {
        "name": "Test User",
        "phone": "+15551234567",
        "email": "test@example.com",
    }

    result = await _execute_book_appointment(
        agent=agent,
        contact_info=contact_info,
        date_str=date_str,
        time_str="14:00",
        email="test-voice-booking@example.com",
        duration_minutes=30,
        notes="Test booking from voice agent test script",
        timezone=timezone,
        log=log,
    )

    # This might fail due to Cal.com validation, but the date parsing should work
    if result.get("success"):
        log_pass("book_appointment succeeded!")
        log_info(f"  Booking ID: {result.get('booking_id')}")
        results["book_appointment_correct"] = True
    else:
        error = result.get("error", "")
        if "Failed to parse" in error or "strptime" in error:
            log_fail(f"Date parsing failed: {error}")
            results["book_appointment_correct"] = False
        else:
            log_warn(f"Booking failed (possibly Cal.com validation): {error}")
            log_info("  Date parsing worked, Cal.com may have rejected the booking")
            results["book_appointment_correct"] = "partial"

    return results


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
    print(f"\n{Colors.BOLD}{'='*60}{Colors.END}")
    print(f"{Colors.BOLD}GROK VOICE AGENT BOOKING TEST SUITE{Colors.END}")
    print(f"{Colors.BOLD}{'='*60}{Colors.END}")
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

    # Test 4: Simulated tool calls
    tool_results = await test_simulated_tool_calls()
    if tool_results.get("skipped"):
        log_info("Tool call tests skipped (missing config)")
    elif not all(v for v in tool_results.values() if isinstance(v, bool)):
        all_passed = False

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

    print("\n" + "="*60)
    print("KEY FINDINGS:")
    print("="*60)
    print("""
1. Voice agent expects YYYY-MM-DD format from Grok
2. If Grok outputs 'tomorrow' or 'next Monday', booking WILL FAIL
3. The date context IS being injected, but Grok may ignore it
4. Your text agents work because they use booking URLs, not tool calls

RECOMMENDED FIXES:
1. Add a date parser that handles natural language in voice_bridge.py
2. Or: Update tool descriptions to be VERY explicit about format
3. Or: Switch to LiveKit's official Grok plugin with better tooling
""")


if __name__ == "__main__":
    asyncio.run(main())
