"""Deterministic, body-free-after-decision routing for SMS model cost control."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

SMSRouteTier = Literal["cheap", "strong"]

_PRICING_PATTERN = re.compile(
    r"\b(price|pricing|cost|quote|estimate|deposit|invoice|refund|discount|fee|rate)\b",
    re.IGNORECASE,
)
_BOOKING_PATTERN = re.compile(
    r"\b(book|booking|appointment|schedule|availability|available|reschedule|cancel)\b",
    re.IGNORECASE,
)
_OPTOUT_PATTERN = re.compile(
    r"\b(stop|unsubscribe|opt[ -]?out|remove me|do not (?:text|call)|don['’]?t (?:text|call))\b",
    re.IGNORECASE,
)
_HANDOFF_PATTERN = re.compile(
    r"\b(human|person|manager|representative|live agent|team member)\b",
    re.IGNORECASE,
)
_MUTABLE_STATE_PATTERN = re.compile(
    r"\b(status|confirmed|approved|accepted|paid|due|open|closed|completed|pending)\b",
    re.IGNORECASE,
)
_CROSS_CHANNEL_PATTERN = re.compile(
    r"\b(called|phone|voicemail|texted|emailed|spoke|earlier|yesterday|last (?:call|text))\b",
    re.IGNORECASE,
)
_CONFLICT_PATTERN = re.compile(
    r"\b(you said|but you|changed|instead|no longer|that['’]?s wrong|incorrect|conflict)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class SMSRouteDecision:
    """One reproducible model/temperature recommendation for an SMS turn."""

    tier: SMSRouteTier
    model: str
    temperature: float
    reason_codes: tuple[str, ...]


def route_sms_turn(
    turn: str,
    *,
    simple_model: str,
    strong_model: str,
    simple_temperature: float,
    strong_temperature: float,
    has_context_conflict: bool = False,
    requires_tool_action: bool = False,
) -> SMSRouteDecision:
    """Route mutable, high-risk, or complex turns to the stronger configured model.

    The turn is inspected in memory and is not returned or logged. Callers should
    emit only ``reason_codes`` and model metadata through context observability.
    """

    reasons: set[str] = set()
    if _PRICING_PATTERN.search(turn):
        reasons.add("pricing_or_quote")
    if _BOOKING_PATTERN.search(turn):
        reasons.add("booking_or_availability")
    if _OPTOUT_PATTERN.search(turn):
        reasons.add("opt_out")
    if _HANDOFF_PATTERN.search(turn):
        reasons.add("human_handoff")
    if _MUTABLE_STATE_PATTERN.search(turn):
        reasons.add("mutable_state")
    if _CROSS_CHANNEL_PATTERN.search(turn):
        reasons.add("cross_channel")
    if has_context_conflict or _CONFLICT_PATTERN.search(turn):
        reasons.add("conflicting_state")
    if requires_tool_action:
        reasons.add("tool_action")
    if len(turn) > 240 or turn.count("?") > 1:
        reasons.add("complex_turn")

    if reasons:
        return SMSRouteDecision(
            tier="strong",
            model=strong_model,
            temperature=strong_temperature,
            reason_codes=tuple(sorted(reasons)),
        )
    return SMSRouteDecision(
        tier="cheap",
        model=simple_model,
        temperature=simple_temperature,
        reason_codes=("simple_turn",),
    )
