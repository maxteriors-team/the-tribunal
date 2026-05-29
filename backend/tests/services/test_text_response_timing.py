"""Tests for human-like text response timing."""

from app.services.ai.text_response_timing import (
    TEXT_RESPONSE_MAX_DELAY_MS,
    TEXT_RESPONSE_MIN_DELAY_MS,
    calculate_text_response_delay_ms,
    clamp_text_response_delay_ms,
)


def test_clamp_text_response_delay_uses_realistic_bounds() -> None:
    assert clamp_text_response_delay_ms(2_000) == TEXT_RESPONSE_MIN_DELAY_MS
    assert clamp_text_response_delay_ms(30_000) == 30_000
    assert clamp_text_response_delay_ms(300_000) == TEXT_RESPONSE_MAX_DELAY_MS


def test_short_text_response_waits_at_least_configured_minimum() -> None:
    delay_ms = calculate_text_response_delay_ms(
        response_text="Yep, sounds good.",
        minimum_delay_ms=22_000,
    )

    assert delay_ms == 22_000


def test_longer_text_response_scales_by_word_count() -> None:
    response_text = " ".join(["word"] * 60)
    delay_ms = calculate_text_response_delay_ms(
        response_text=response_text,
        minimum_delay_ms=22_000,
    )

    assert delay_ms == 90_000


def test_very_long_text_response_caps_at_three_minutes() -> None:
    response_text = " ".join(["word"] * 200)
    delay_ms = calculate_text_response_delay_ms(
        response_text=response_text,
        minimum_delay_ms=22_000,
    )

    assert delay_ms == TEXT_RESPONSE_MAX_DELAY_MS
