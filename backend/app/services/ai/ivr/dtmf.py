"""DTMF parsing and validation for IVR navigation."""

import re

import structlog

from app.services.ai.ivr.types import DTMFContext

logger = structlog.get_logger()


class DTMFValidator:
    """Validate and split DTMF based on context."""

    def split_dtmf_by_context(self, digits: str, context: DTMFContext) -> list[str]:
        """Split multi-digit string based on IVR context.

        Examples:
            ("220", MENU) -> ["2", "2", "0"]  # Individual presses
            ("220", EXTENSION) -> ["220#"]     # Together with terminator

        Args:
            digits: The DTMF digits to split
            context: The IVR context indicating expected input type

        Returns:
            List of DTMF sequences to send
        """
        if context == DTMFContext.MENU:
            return list(digits)  # Split into individual
        elif context == DTMFContext.EXTENSION:
            return [f"{digits}#"] if not digits.endswith("#") else [digits]
        elif context in {DTMFContext.PIN}:
            return [digits]  # Together, no terminator
        else:
            # Unknown: default to individual (safe)
            return list(digits)


class DTMFParser:
    """Extract and strip DTMF tags from agent responses.

    The voice agent LLM can include <dtmf>X</dtmf> tags in its response
    to indicate digits that should be sent to navigate IVR menus.

    Example:
        Input: "I'll press 1 for sales <dtmf>1</dtmf>"
        Output: ["1"]
        Stripped: "I'll press 1 for sales"
    """

    def __init__(self, pattern: str = r"<dtmf>([0-9*#A-Dw]+)</dtmf>") -> None:
        """Initialize parser with DTMF tag pattern.

        Args:
            pattern: Regex pattern with capture group for digits.
                     Valid chars: 0-9, *, #, A-D, w (pause)
        """
        self._pattern = re.compile(pattern, re.IGNORECASE)
        self.logger = logger.bind(service="dtmf_parser")

    def parse(self, text: str) -> list[str]:
        """Extract DTMF digits from text.

        Args:
            text: Agent response text

        Returns:
            List of DTMF digit strings found
        """
        if not text:
            return []

        matches = self._pattern.findall(text)

        if matches:
            self.logger.info(
                "dtmf_tags_found",
                digits=matches,
                text_preview=text[:100],
            )

        return matches

    def strip_dtmf_tags(self, text: str) -> str:
        """Remove DTMF tags from text.

        Args:
            text: Agent response text with possible DTMF tags

        Returns:
            Text with DTMF tags removed
        """
        if not text:
            return ""

        return self._pattern.sub("", text).strip()
