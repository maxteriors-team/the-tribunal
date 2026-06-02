#!/usr/bin/env python3
"""Stress test script for Jess | PRESTYJ Sales Agent text capabilities.

This script simulates various customer interactions to test:
1. Basic greetings and responses
2. Sales conversation flow
3. Qualification process
4. Booking workflow
5. Edge cases (rude, confused, off-topic)
6. Email collection
7. Objection handling
"""

import asyncio
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

# Add backend to path
import sys
sys.path.insert(0, '/home/groot/aicrm/backend')

from sqlalchemy import select, text
from app.db.session import AsyncSessionLocal
from app.models.agent import Agent
from app.models.conversation import Conversation, Message
from app.services.ai.text_prompt_builder import build_text_instructions
from app.services.ai.text_response_generator import generate_text_response
from app.core.config import settings


AGENT_ID = "5bba3103-f3e0-4eb8-bec0-5423bf4051d4"
WORKSPACE_ID = "ba0e0e99-c7c9-45ec-9625-567d54d6e9c2"


@dataclass
class TestCase:
    """A single test case for the text agent."""
    name: str
    messages: list[str]  # Simulated inbound messages
    expected_behaviors: list[str]  # What we expect to see in responses
    category: str


@dataclass
class TestResult:
    """Result of a single test case."""
    test_case: TestCase
    responses: list[str]
    passed: bool
    notes: str
    duration_ms: float


# Define test scenarios with more flexible expected behaviors
TEST_CASES = [
    # Category: Basic Greetings
    TestCase(
        name="Simple Hello",
        messages=["Hi"],
        expected_behaviors=["hello", "help", "assist"],  # More flexible
        category="greetings"
    ),
    TestCase(
        name="Question About Service",
        messages=["What do you guys do?"],
        expected_behaviors=["AI", "lead", "appointment"],  # Core value prop
        category="greetings"
    ),
    TestCase(
        name="Who Is This",
        messages=["Who is this?"],
        expected_behaviors=["Jess", "PRESTYJ"],  # Identity
        category="greetings"
    ),

    # Category: Qualification
    TestCase(
        name="Interested Lead",
        messages=[
            "Hi there",
            "I'm a realtor in Miami",
            "Yeah I struggle with following up on leads quickly"
        ],
        expected_behaviors=["?", "lead", "follow"],  # Asks question, mentions leads
        category="qualification"
    ),
    TestCase(
        name="Volume Question",
        messages=[
            "How many leads can your system handle?",
        ],
        expected_behaviors=["unlimited", "handle"],  # Key capacity answer
        category="qualification"
    ),
    TestCase(
        name="Price Question",
        messages=["How much does it cost?"],
        expected_behaviors=["5,000", "25,000"],  # Accept comma formatting
        category="qualification"
    ),

    # Category: Booking Flow
    TestCase(
        name="Ready to Book",
        messages=[
            "I'd like to learn more",
            "Yes I'm interested in scheduling a call",
        ],
        expected_behaviors=["available", "time", "email"],  # Booking flow
        category="booking"
    ),
    TestCase(
        name="Specific Time Request",
        messages=[
            "Can we do a call tomorrow at 2pm?",
        ],
        expected_behaviors=["available", "PM", "email"],  # Offers alternatives
        category="booking"
    ),
    TestCase(
        name="Email Collection",
        messages=[
            "Let's schedule something",
            "Tomorrow afternoon works",
            "john.smith@realty.com",
        ],
        expected_behaviors=["time", "PM"],  # Should use email and book
        category="booking"
    ),

    # Category: Objection Handling
    TestCase(
        name="Too Expensive Objection",
        messages=["That's too expensive for me"],
        expected_behaviors=["understand", "?"],  # Acknowledges, asks question
        category="objections"
    ),
    TestCase(
        name="Already Have a System",
        messages=["I already have a CRM and follow-up system"],
        expected_behaviors=["?", "working"],  # Asks how it's working
        category="objections"
    ),
    TestCase(
        name="Not Interested",
        messages=["I'm not interested"],
        expected_behaviors=["understand", "reach out"],  # Graceful exit
        category="objections"
    ),
    TestCase(
        name="Need to Think About It",
        messages=["I need to think about it"],
        expected_behaviors=["understand", "time"],  # Respects decision
        category="objections"
    ),

    # Category: Edge Cases
    TestCase(
        name="Empty/Short Message",
        messages=["ok"],
        expected_behaviors=["?", "assist"],  # Asks clarifying question
        category="edge_cases"
    ),
    TestCase(
        name="Rude Response",
        messages=["Stop texting me this is spam"],
        expected_behaviors=["stop", "understand"],  # NO booking attempt
        category="edge_cases"
    ),
    TestCase(
        name="Off Topic Question",
        messages=["What's the weather like today?"],
        expected_behaviors=["real estate", "lead"],  # Redirects to service
        category="edge_cases"
    ),
    TestCase(
        name="Competitor Mention",
        messages=["How are you different from Follow Up Boss or Ylopo?"],
        expected_behaviors=["AI", "90 days"],  # Differentiator
        category="edge_cases"
    ),
    TestCase(
        name="Rapid Fire Questions",
        messages=["What's the price, timeline, and guarantee?"],
        expected_behaviors=["5,000", "90"],  # Answers all three
        category="edge_cases"
    ),
    TestCase(
        name="Confusion Test",
        messages=["Wait what? I don't understand what you're selling"],
        expected_behaviors=["AI", "lead", "appointment"],  # Clear explanation
        category="edge_cases"
    ),

    # Category: Multi-turn Conversations
    TestCase(
        name="Full Sales Flow",
        messages=[
            "Hey",
            "I'm a real estate agent in Texas",
            "Yeah I lose a lot of deals because I can't respond fast enough",
            "Maybe 5-10 leads a week",
            "Usually within a few hours, sometimes the next day",
            "About 20% convert to appointments",
            "What exactly would your system do?",
            "That sounds interesting. What's the investment?",
        ],
        expected_behaviors=["AI", "5,000", "appointment"],  # Key points
        category="full_flow"
    ),
]


async def create_mock_conversation(db, messages: list[str]) -> tuple[Conversation, Agent]:
    """Create a mock conversation with message history."""
    # Get agent
    result = await db.execute(
        select(Agent).where(Agent.id == uuid.UUID(AGENT_ID))
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise ValueError(f"Agent {AGENT_ID} not found")

    # Create a temporary conversation
    conversation = Conversation(
        id=uuid.uuid4(),
        workspace_id=uuid.UUID(WORKSPACE_ID),
        contact_phone="+15551234567",
        workspace_phone="+12485309314",
        channel="sms",
        ai_enabled=True,
        ai_paused=False,
        assigned_agent_id=agent.id,
        last_message_at=datetime.now(UTC),
    )
    db.add(conversation)
    await db.flush()

    # Add messages
    for i, body in enumerate(messages):
        msg = Message(
            conversation_id=conversation.id,
            direction="inbound",
            channel="sms",
            body=body,
            status="received",
        )
        db.add(msg)

    await db.flush()
    return conversation, agent


async def run_test_case(test_case: TestCase) -> TestResult:
    """Run a single test case and return results."""
    start = datetime.now()
    responses: list[str] = []
    notes_parts: list[str] = []

    try:
        async with AsyncSessionLocal() as db:
            # Create conversation with message history
            conversation, agent = await create_mock_conversation(db, test_case.messages)

            # Generate response
            if not settings.openai_api_key:
                return TestResult(
                    test_case=test_case,
                    responses=[],
                    passed=False,
                    notes="No OpenAI API key configured",
                    duration_ms=0
                )

            response = await generate_text_response(
                agent=agent,
                conversation=conversation,
                db=db,
                openai_api_key=settings.openai_api_key,
            )

            if response:
                responses.append(response)
            else:
                notes_parts.append("No response generated")

            # Rollback to not persist test data
            await db.rollback()

    except Exception as e:
        notes_parts.append(f"Error: {str(e)}")

    duration = (datetime.now() - start).total_seconds() * 1000

    # Check expected behaviors
    response_lower = " ".join(responses).lower()
    matched = []
    missed = []

    for behavior in test_case.expected_behaviors:
        if behavior.lower() in response_lower:
            matched.append(behavior)
        else:
            missed.append(behavior)

    # Determine pass/fail (at least 50% of expected behaviors)
    passed = len(matched) >= len(test_case.expected_behaviors) / 2

    if matched:
        notes_parts.append(f"Matched: {', '.join(matched)}")
    if missed:
        notes_parts.append(f"Missed: {', '.join(missed)}")

    return TestResult(
        test_case=test_case,
        responses=responses,
        passed=passed,
        notes="; ".join(notes_parts) if notes_parts else "OK",
        duration_ms=duration
    )


async def run_stress_test():
    """Run all test cases and report results."""
    print("=" * 80)
    print("JESS | PRESTYJ SALES AGENT - STRESS TEST")
    print("=" * 80)
    print(f"Agent ID: {AGENT_ID}")
    print(f"Total Test Cases: {len(TEST_CASES)}")
    print("=" * 80)

    results: list[TestResult] = []
    categories: dict[str, list[TestResult]] = {}

    for i, test_case in enumerate(TEST_CASES):
        print(f"\n[{i+1}/{len(TEST_CASES)}] Testing: {test_case.name} ({test_case.category})")
        print(f"  Input: {test_case.messages[-1][:60]}...")

        result = await run_test_case(test_case)
        results.append(result)

        if test_case.category not in categories:
            categories[test_case.category] = []
        categories[test_case.category].append(result)

        status = "PASS" if result.passed else "FAIL"
        print(f"  Status: {status} ({result.duration_ms:.0f}ms)")
        if result.responses:
            response_preview = result.responses[0][:150]
            print(f"  Response: {response_preview}...")
        print(f"  Notes: {result.notes}")

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)

    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed
    total_time = sum(r.duration_ms for r in results)

    print(f"\nOverall: {passed}/{len(results)} passed ({100*passed/len(results):.1f}%)")
    print(f"Total Time: {total_time/1000:.1f}s (avg: {total_time/len(results):.0f}ms per test)")

    print("\nBy Category:")
    for category, cat_results in categories.items():
        cat_passed = sum(1 for r in cat_results if r.passed)
        print(f"  {category}: {cat_passed}/{len(cat_results)} passed")

    print("\nFailed Tests:")
    for result in results:
        if not result.passed:
            print(f"  - {result.test_case.name}: {result.notes}")

    # Print all responses for review
    print("\n" + "=" * 80)
    print("ALL RESPONSES (for review)")
    print("=" * 80)
    for result in results:
        print(f"\n### {result.test_case.name} ###")
        print(f"Input: {' -> '.join(result.test_case.messages)}")
        print(f"Response: {result.responses[0] if result.responses else 'NO RESPONSE'}")
        print("-" * 40)

    return results


async def quick_test_single(message: str):
    """Quick test a single message for debugging."""
    print(f"Testing: '{message}'")
    print("-" * 40)

    async with AsyncSessionLocal() as db:
        conversation, agent = await create_mock_conversation(db, [message])

        response = await generate_text_response(
            agent=agent,
            conversation=conversation,
            db=db,
            openai_api_key=settings.openai_api_key,
        )

        print(f"Response: {response}")
        await db.rollback()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Stress test Jess text agent")
    parser.add_argument("--quick", type=str, help="Quick test a single message")
    parser.add_argument("--category", type=str, help="Only run tests in this category")
    args = parser.parse_args()

    if args.quick:
        asyncio.run(quick_test_single(args.quick))
    else:
        # Filter by category if specified
        if args.category:
            TEST_CASES[:] = [t for t in TEST_CASES if t.category == args.category]
        asyncio.run(run_stress_test())
