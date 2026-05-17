"""Rule-based IVR, human, and voicemail classifier."""

import re

import structlog

from app.services.ai.ivr.types import DTMFContext, IVRMode

logger = structlog.get_logger()


class IVRClassifier:
    """Rule-based classifier for IVR, human, and voicemail detection.

    Uses regex patterns to quickly classify transcripts without API latency.
    Patterns are based on common IVR menu phrases and human speech indicators.

    IMPORTANT: When exclusive IVR patterns (DTMF prompts) are detected, the
    classifier will ALWAYS return IVR, even if voicemail patterns also match.
    This prevents misclassification of "Press 1 to leave a message" as voicemail.
    """

    # EXCLUSIVE IVR patterns - DTMF prompts that indicate a navigable menu
    # If ANY of these match, the transcript is ALWAYS IVR, never voicemail
    # These are patterns where user input is expected/requested
    EXCLUSIVE_IVR_PATTERNS: list[str] = [
        r"press\s+[0-9*#]",  # "Press 1", "Press 2", "Press star"
        r"dial\s+[0-9*#]",  # "Dial 0 for operator"
        r"for\s+\w+\s*,?\s*press",  # "For sales, press 1"
        r"to\s+\w+\s*,?\s*press",  # "To speak to a representative, press 0"
        r"option\s+[0-9]",  # "Option 1 is for billing"
        r"say\s+or\s+press",  # "Say or press 1"
        r"enter\s+your\s+(account|pin|phone|extension)",  # "Enter your account number"
    ]

    # IVR error/retry patterns - indicate IVR detected invalid input
    # These messages mean we're still in IVR mode and need to retry
    # NOTE: Patterns must be specific to avoid false positives with voicemail
    IVR_ERROR_PATTERNS: list[str] = [
        r"is\s+not\s+a\s+valid\s+extension",  # "That is not a valid extension"
        r"invalid\s+(selection|option|entry|input)",  # "Invalid selection"
        r"please\s+try\s+again\b(?!\s+later)",  # "Please try again" but NOT "try again later"
        r"that\s+is\s+not\s+(a\s+valid\s+)?an?\s+option",  # "That is not an option"
        r"did\s+not\s+(recognize|understand)",  # "I did not recognize your input"
        r"not\s+a\s+valid\s+(option|selection|choice|entry)",  # "Not a valid option"
        r"incorrect\s+(entry|selection|choice|input)",  # "Incorrect entry"
        r"unrecognized\s+(input|selection)",  # "Unrecognized input"
    ]

    # IVR menu patterns - phrases that indicate automated phone systems
    # (Does NOT include "leave a message" or "at the beep" which are voicemail-only)
    IVR_PATTERNS: list[str] = [
        r"press\s+[0-9*#]",
        r"dial\s+[0-9*#]",
        r"for\s+\w+\s*,?\s*press",
        r"to\s+speak\s+\w+\s*,?\s*press",
        r"say\s+or\s+press",
        r"enter\s+your",
        r"please\s+enter",
        r"main\s+menu",
        r"previous\s+menu",
        r"return\s+to\s+the\s+menu",
        r"listen\s+to\s+these\s+options",
        r"following\s+options",
        r"option\s+[0-9]",
        r"extension\s+[0-9]",
        r"if\s+you\s+know\s+your\s+party'?s?\s+extension",
        r"your\s+call\s+is\s+important",
        r"please\s+hold",
        r"all\s+(of\s+)?our\s+(representatives|agents|operators)",
        r"currently\s+(experiencing|assisting)",
        r"hold\s+for\s+the\s+next\s+available",
        r"estimated\s+wait\s+time",
        r"queue\s+position",
        r"thank\s+you\s+for\s+calling",
        r"business\s+hours\s+are",
        r"we\s+are\s+(currently\s+)?closed",
    ]

    # Human conversation patterns - indicate a real person
    HUMAN_PATTERNS: list[str] = [
        r"how\s+(can|may)\s+i\s+help",
        r"my\s+name\s+is",
        r"this\s+is\s+\w+\s+speaking",
        r"speaking",  # "Hello, this is John speaking"
        r"what\s+can\s+i\s+do\s+for\s+you",
        r"how\s+are\s+you",
        r"good\s+(morning|afternoon|evening)",
        r"thanks\s+for\s+calling",
        r"sorry\s+(about\s+that|to\s+hear)",
        r"let\s+me\s+(check|look|see|help)",
        r"one\s+(moment|second)",
        r"i('ll|'m\s+going\s+to)",
        r"we('ll|'re\s+going\s+to)",
        r"absolutely",
        r"definitely",
        r"no\s+problem",
        r"of\s+course",
    ]

    # Voicemail patterns - ONLY match when NO exclusive IVR patterns present
    VOICEMAIL_PATTERNS: list[str] = [
        r"leave\s+a\s+(voice\s*)?message",
        r"at\s+the\s+(tone|beep)",
        r"after\s+the\s+(tone|beep)",
        r"record\s+your\s+message",
        r"mailbox\s+(is\s+)?full",
        r"voice\s*mail(\s+box)?",
        r"not\s+available\s+to\s+take\s+your\s+call",
        r"please\s+leave\s+your\s+name\s+and\s+number",
        r"we('ll)?\s+get\s+back\s+to\s+you",
    ]

    def __init__(self) -> None:
        """Initialize classifier with compiled regex patterns."""
        self._exclusive_ivr_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.EXCLUSIVE_IVR_PATTERNS
        ]
        self._ivr_error_patterns = [re.compile(p, re.IGNORECASE) for p in self.IVR_ERROR_PATTERNS]
        self._ivr_patterns = [re.compile(p, re.IGNORECASE) for p in self.IVR_PATTERNS]
        self._human_patterns = [re.compile(p, re.IGNORECASE) for p in self.HUMAN_PATTERNS]
        self._voicemail_patterns = [re.compile(p, re.IGNORECASE) for p in self.VOICEMAIL_PATTERNS]
        self.logger = logger.bind(service="ivr_classifier")

    def classify(self, transcript: str) -> tuple[IVRMode, float]:
        """Classify a transcript as IVR, human, or voicemail.

        Priority order:
        1. If ANY exclusive IVR pattern matches (DTMF prompts) -> IVR (always)
        2. If human patterns dominate -> CONVERSATION
        3. If voicemail patterns match AND no IVR patterns -> VOICEMAIL
        4. If IVR patterns match -> IVR
        5. Otherwise -> UNKNOWN

        Args:
            transcript: Speech transcript to classify

        Returns:
            Tuple of (classification mode, confidence score 0.0-1.0)
        """
        if not transcript or len(transcript.strip()) < 5:
            return IVRMode.UNKNOWN, 0.0

        text = transcript.lower().strip()
        counts = self._count_pattern_matches(text)

        self.logger.debug("ivr_classification", transcript_preview=text[:100], **counts)

        return self._determine_mode(counts)

    def _count_pattern_matches(self, text: str) -> dict[str, int]:
        """Count pattern matches for each category."""
        exclusive = sum(1 for p in self._exclusive_ivr_patterns if p.search(text))
        ivr_error = sum(1 for p in self._ivr_error_patterns if p.search(text))
        ivr = sum(1 for p in self._ivr_patterns if p.search(text))
        human = sum(1 for p in self._human_patterns if p.search(text))
        voicemail = sum(1 for p in self._voicemail_patterns if p.search(text))

        return {
            "exclusive_ivr_matches": exclusive,
            "ivr_error_matches": ivr_error,
            "ivr_matches": ivr,
            "human_matches": human,
            "voicemail_matches": voicemail,
            "total_matches": ivr + ivr_error + human + voicemail,
        }

    def _determine_mode(self, counts: dict[str, int]) -> tuple[IVRMode, float]:
        """Determine mode based on pattern match counts."""
        exclusive = counts["exclusive_ivr_matches"]
        ivr_error = counts["ivr_error_matches"]
        ivr = counts["ivr_matches"]
        human = counts["human_matches"]
        voicemail = counts["voicemail_matches"]
        total = counts["total_matches"]

        # PRIORITY 1: Exclusive IVR patterns ALWAYS win (DTMF prompts)
        # PRIORITY 2: IVR error patterns (invalid input messages)
        # Both indicate we're in IVR mode
        if exclusive > 0 or ivr_error > 0:
            ratio = (exclusive + ivr + ivr_error) / max(1, total)
            # Slightly lower confidence boost for error-only matches
            boost = 0.3 if exclusive > 0 else 0.25
            return IVRMode.IVR, min(1.0, ratio + boost)

        # No patterns matched
        if total == 0:
            return IVRMode.UNKNOWN, 0.0

        # PRIORITY 3: Human patterns dominate
        if human > ivr and human > voicemail:
            return IVRMode.CONVERSATION, min(1.0, human / total + 0.2)

        # PRIORITY 4: Voicemail ONLY if no IVR patterns
        if voicemail > 0 and ivr == 0:
            return IVRMode.VOICEMAIL, min(1.0, voicemail / total + 0.2)

        # PRIORITY 5: IVR patterns present (or tie/unclear -> unknown)
        if ivr > 0:
            return IVRMode.IVR, min(1.0, ivr / total + 0.2)

        return IVRMode.UNKNOWN, 0.3

    def detect_context(self, transcript: str) -> DTMFContext:
        """Detect what type of DTMF input is expected.

        Args:
            transcript: The IVR menu transcript

        Returns:
            DTMFContext indicating expected input type
        """
        text = transcript.lower()

        if re.search(r"enter.*extension|dial.*extension", text):
            return DTMFContext.EXTENSION
        if re.search(r"enter.*pin|enter.*password", text):
            return DTMFContext.PIN
        if re.search(r"leave.*message|after.*beep", text):
            return DTMFContext.VOICEMAIL
        if re.search(r"press\s+[0-9]|option\s+[0-9]", text):
            return DTMFContext.MENU

        return DTMFContext.UNKNOWN
