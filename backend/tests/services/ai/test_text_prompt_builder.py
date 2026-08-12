"""Regression tests for customer-facing SMS prompt behavior."""

from app.services.ai.text_prompt_builder import (
    build_booking_instructions,
    build_text_instructions,
)


def test_text_prompt_requires_human_concise_truthful_replies() -> None:
    prompt = build_text_instructions("You help customers book estimates.")

    assert "helpful person texting" in prompt
    assert "one short message" in prompt
    assert "Never repeat a confirmation" in prompt
    assert "appears mistyped, ask a brief clarifying question" in prompt
    assert "tool result in THIS response proves it" in prompt


def test_booking_prompt_prevents_scott_conversation_failures() -> None:
    prompt = build_booking_instructions("America/New_York")

    assert "send exactly ONE concise confirmation" in prompt
    assert "invitation_sent is true" in prompt
    assert "did the invite email not arrive" in prompt
    assert "never claim you changed them" in prompt
