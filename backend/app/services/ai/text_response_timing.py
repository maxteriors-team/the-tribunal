"""Human-like timing helpers for AI text conversations."""

from app.constants.text_response_timing import (
    TEXT_RESPONSE_MAX_DELAY_MS,
    TEXT_RESPONSE_MIN_DELAY_MS,
)

_TEXT_RESPONSE_SECONDS_PER_WORD = 1.5


def clamp_text_response_delay_ms(delay_ms: int) -> int:
    """Clamp configured text-response delay to realistic supported bounds."""
    return max(TEXT_RESPONSE_MIN_DELAY_MS, min(delay_ms, TEXT_RESPONSE_MAX_DELAY_MS))


def calculate_text_response_delay_ms(response_text: str, minimum_delay_ms: int) -> int:
    """Return a human-like delay based on response length.

    The configured agent delay is treated as the minimum. Short messages still wait
    at least ~22 seconds, while longer replies scale by approximate reading/typing
    effort and cap at three minutes.
    """
    normalized_words = response_text.split()
    word_based_delay_ms = round(len(normalized_words) * _TEXT_RESPONSE_SECONDS_PER_WORD * 1000)
    return min(
        TEXT_RESPONSE_MAX_DELAY_MS,
        max(clamp_text_response_delay_ms(minimum_delay_ms), word_based_delay_ms),
    )
