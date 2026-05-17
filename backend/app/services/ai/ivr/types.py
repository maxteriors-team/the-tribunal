"""IVR type definitions: enums and dataclasses."""

from dataclasses import dataclass, field
from enum import Enum


class IVRMode(Enum):
    """Operating mode for voice agent during a call."""

    UNKNOWN = "unknown"
    CONVERSATION = "conversation"  # Normal human conversation
    IVR = "ivr"  # Automated phone menu detected
    VOICEMAIL = "voicemail"  # Voicemail system detected


class DTMFContext(Enum):
    """Context for DTMF input expectations."""

    UNKNOWN = "unknown"
    MENU = "menu"  # Single digit (1-9, 0, *, #)
    EXTENSION = "extension"  # Multi-digit with # terminator
    PIN = "pin"  # Multi-digit PIN
    VOICEMAIL = "voicemail"  # Don't press buttons


@dataclass
class IVRMenuState:
    """State of current IVR menu."""

    context: DTMFContext = DTMFContext.UNKNOWN
    attempted_dtmf: set[str] = field(default_factory=set)
    failed_dtmf: set[str] = field(default_factory=set)
    last_menu_text: str | None = None


@dataclass
class IVRDetectorConfig:
    """Configuration for IVR detection behavior.

    Attributes:
        loop_similarity_threshold: TF-IDF similarity threshold for loop detection (0.0-1.0)
        consecutive_classifications: Number of consistent classifications before mode switch
        dtmf_tag_pattern: Regex pattern to extract DTMF digits from agent responses
        max_transcript_history: Maximum transcripts to keep for loop detection
        min_transcript_length: Minimum transcript length to classify (ignore short utterances)
    """

    loop_similarity_threshold: float = 0.85
    consecutive_classifications: int = 2
    dtmf_tag_pattern: str = r"<dtmf>([0-9*#A-Dw]+)</dtmf>"
    max_transcript_history: int = 10
    min_transcript_length: int = 10


@dataclass
class IVRStatus:
    """Current IVR detection status.

    Attributes:
        mode: Current operating mode
        loop_detected: Whether an IVR loop has been detected
        consecutive_ivr_count: Consecutive IVR classifications
        consecutive_human_count: Consecutive human classifications
        last_dtmf_sent: Last DTMF digits detected/sent
        attempted_dtmf: Set of all DTMF digits that have been tried
        failed_dtmf: Set of DTMF digits that didn't change the menu
        last_menu_transcript: Last menu transcript for change detection
        menu_state: Current IVR menu state
    """

    mode: IVRMode = IVRMode.UNKNOWN
    loop_detected: bool = False
    consecutive_ivr_count: int = 0
    consecutive_human_count: int = 0
    last_dtmf_sent: str | None = None
    attempted_dtmf: set[str] = field(default_factory=set)
    failed_dtmf: set[str] = field(default_factory=set)
    last_menu_transcript: str | None = None
    menu_state: IVRMenuState = field(default_factory=IVRMenuState)
