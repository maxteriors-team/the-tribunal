"""Scripted IVR navigator - extracts menu options and selects DTMF digits without AI."""

import re
from dataclasses import dataclass, field
from enum import Enum

import structlog

logger = structlog.get_logger()

# Keywords and their synonyms for goal matching
GOAL_SYNONYMS: dict[str, set[str]] = {
    "human": {"representative", "agent", "operator", "person", "someone", "staff", "receptionist"},
    "sales": {"sell", "selling", "purchase", "buy", "buying", "order", "ordering"},
    "support": {"help", "assistance", "service", "technical", "tech"},
    "billing": {"payment", "account", "invoice", "bill", "pay", "balance"},
    "appointment": {"schedule", "booking", "book", "reserve", "reservation", "calendar"},
    "speak": {"talk", "reach", "connect", "transfer"},
}


class NavigationAction(Enum):
    """Action to take after selecting a digit."""

    PRESS_DIGIT = "press_digit"
    FALLBACK_AI = "fallback_ai"
    NO_ACTION = "no_action"


@dataclass
class MenuOption:
    """A parsed menu option from IVR transcript."""

    digit: str
    description: str


@dataclass
class NavigationResult:
    """Result of navigation decision."""

    action: NavigationAction
    digit: str = ""
    reason: str = ""


@dataclass
class ScriptedNavigator:
    """Extracts menu options and navigates IVR menus using regex + keyword matching.

    Tracks attempted/failed digits to avoid loops and exhaustion.

    Args:
        navigation_goal: What the caller is trying to reach (e.g., "Reach a human representative")
        max_attempts: Maximum navigation attempts before falling back to AI
    """

    navigation_goal: str = "Reach a human representative"
    max_attempts: int = 8
    _attempted: set[str] = field(default_factory=set)
    _failed: set[str] = field(default_factory=set)
    _attempt_count: int = 0
    _log: structlog.stdlib.BoundLogger = field(
        default_factory=lambda: logger.bind(service="scripted_navigator")
    )

    # Regex patterns for extracting menu options
    _MENU_PATTERNS: list[str] = field(
        default_factory=lambda: [
            r"press\s+(\d+|star|\*|pound|#)\s+(?:for|to)\s+(.+?)(?:\.|,|$)",
            r"for\s+(.+?)\s*,?\s*press\s+(\d+|star|\*|pound|#)",
            r"to\s+(.+?)\s*,?\s*press\s+(\d+|star|\*|pound|#)",
            r"option\s+(\d+|star|\*|pound|#)\s+(?:for|is|to)\s+(.+?)(?:\.|,|$)",
            r"(?:say|dial)\s+or\s+press\s+(\d+|star|\*|pound|#)\s+(?:for|to)\s+(.+?)(?:\.|,|$)",
        ]
    )

    def extract_menu_options(self, transcript: str) -> list[MenuOption]:
        """Extract menu options from an IVR transcript.

        Args:
            transcript: IVR menu transcript text

        Returns:
            List of parsed menu options with digit and description
        """
        options: list[MenuOption] = []
        text = transcript.lower().strip()
        seen_digits: set[str] = set()

        for i, pattern in enumerate(self._MENU_PATTERNS):
            for match in re.finditer(pattern, text, re.IGNORECASE):
                if i in {0, 3, 4}:
                    # "press X for Y" / "option X for Y" / "say or press X for Y"
                    raw_digit, description = match.group(1), match.group(2)
                else:
                    # "for Y press X" / "to Y press X"
                    description, raw_digit = match.group(1), match.group(2)

                digit = self._normalize_digit(raw_digit)
                if digit and digit not in seen_digits:
                    seen_digits.add(digit)
                    options.append(MenuOption(digit=digit, description=description.strip()))

        self._log.debug(
            "menu_options_extracted",
            count=len(options),
            options=[(o.digit, o.description) for o in options],
        )
        return options

    def select_digit(self, transcript: str) -> NavigationResult:
        """Decide which digit to press based on transcript and navigation goal.

        Decision algorithm:
        1. Extract options -> score against goal keywords
        2. Fallback: press 0 (operator) if untried
        3. Fallback: try untried extracted options
        4. Fallback: try digits 1-9 sequentially
        5. Exhausted: return fallback_ai

        Args:
            transcript: IVR menu transcript

        Returns:
            NavigationResult with action, digit, and reason
        """
        self._attempt_count += 1

        if self._attempt_count > self.max_attempts:
            return NavigationResult(
                action=NavigationAction.FALLBACK_AI,
                reason=f"exhausted max attempts ({self.max_attempts})",
            )

        options = self.extract_menu_options(transcript)

        # Step 1: Score options against navigation goal
        if options:
            best = self._score_options(options)
            if best and best.digit not in self._attempted:
                self._log.info(
                    "goal_matched_option",
                    digit=best.digit,
                    description=best.description,
                    goal=self.navigation_goal,
                )
                return NavigationResult(
                    action=NavigationAction.PRESS_DIGIT,
                    digit=best.digit,
                    reason=f"goal match: {best.description}",
                )

        # Step 2: Try 0 (operator) if untried
        if "0" not in self._attempted:
            self._log.info("fallback_operator", digit="0")
            return NavigationResult(
                action=NavigationAction.PRESS_DIGIT,
                digit="0",
                reason="fallback: operator (0)",
            )

        # Step 3: Try untried extracted options
        for opt in options:
            if opt.digit not in self._attempted:
                self._log.info(
                    "fallback_untried_option",
                    digit=opt.digit,
                    description=opt.description,
                )
                return NavigationResult(
                    action=NavigationAction.PRESS_DIGIT,
                    digit=opt.digit,
                    reason=f"untried option: {opt.description}",
                )

        # Step 4: Try digits 1-9 sequentially
        for d in "123456789":
            if d not in self._attempted:
                self._log.info("fallback_sequential", digit=d)
                return NavigationResult(
                    action=NavigationAction.PRESS_DIGIT,
                    digit=d,
                    reason=f"sequential fallback: {d}",
                )

        # Step 5: Exhausted
        return NavigationResult(
            action=NavigationAction.FALLBACK_AI,
            reason="all digits exhausted",
        )

    def record_attempt(self, digit: str) -> None:
        """Record that a digit was attempted."""
        self._attempted.add(digit)
        self._log.debug("digit_attempted", digit=digit, total_attempted=len(self._attempted))

    def record_failure(self, digit: str) -> None:
        """Record that a digit failed (didn't reach desired state)."""
        self._failed.add(digit)
        self._log.debug("digit_failed", digit=digit, total_failed=len(self._failed))

    def _score_options(self, options: list[MenuOption]) -> MenuOption | None:
        """Score extracted options against the navigation goal.

        Uses keyword set intersection with synonym expansion.

        Returns:
            Best matching option, or None if no good match
        """
        goal_words = self._expand_keywords(self.navigation_goal.lower())
        best_option: MenuOption | None = None
        best_score: float = 0

        for opt in options:
            if opt.digit in self._attempted:
                continue
            desc_words = set(opt.description.lower().split())
            score: float = len(goal_words & desc_words)

            # Also check for partial word matches
            for gw in goal_words:
                for dw in desc_words:
                    if gw in dw or dw in gw:
                        score += 0.5

            if score > best_score:
                best_score = score
                best_option = opt

        return best_option

    @staticmethod
    def _expand_keywords(text: str) -> set[str]:
        """Expand text words with synonyms for broader matching."""
        words = set(text.split())
        expanded = set(words)

        for word in words:
            for _key, synonyms in GOAL_SYNONYMS.items():
                if word in synonyms or word == _key:
                    expanded.add(_key)
                    expanded.update(synonyms)

        return expanded

    @staticmethod
    def _normalize_digit(raw: str) -> str:
        """Normalize spoken digit to DTMF character."""
        raw = raw.strip().lower()
        mapping = {"star": "*", "pound": "#", "hash": "#"}
        return mapping.get(raw, raw) if not raw.isdigit() else raw
