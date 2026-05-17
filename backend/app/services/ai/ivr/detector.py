"""IVR detection orchestrator."""

from collections.abc import Callable
from dataclasses import dataclass, field

import structlog

from app.services.ai.ivr.classifier import IVRClassifier
from app.services.ai.ivr.dtmf import DTMFParser
from app.services.ai.ivr.loop_detector import LoopDetector
from app.services.ai.ivr.types import (
    DTMFContext,
    IVRDetectorConfig,
    IVRMode,
    IVRStatus,
)

logger = structlog.get_logger()


@dataclass
class IVRDetector:
    """Main orchestrator for IVR detection with callbacks.

    Coordinates the classifier, loop detector, and DTMF parser to
    provide a unified interface for IVR detection and navigation.

    Usage:
        detector = IVRDetector(
            config=IVRDetectorConfig(),
            on_mode_change=handle_mode_change,
            on_loop_detected=handle_loop,
            on_dtmf_detected=handle_dtmf,
        )

        # Process incoming transcripts
        mode = await detector.process_transcript(user_speech, is_agent=False)
        mode = await detector.process_transcript(agent_response, is_agent=True)

    Attributes:
        config: Detection configuration
        on_mode_change: Callback for mode changes (old_mode, new_mode)
        on_loop_detected: Callback when IVR loop detected
        on_dtmf_detected: Callback when DTMF digits found (digits string)
    """

    config: IVRDetectorConfig = field(default_factory=IVRDetectorConfig)
    on_mode_change: Callable[[IVRMode, IVRMode], None] | None = None
    on_loop_detected: Callable[[], None] | None = None
    on_dtmf_detected: Callable[[str], None] | None = None

    def __post_init__(self) -> None:
        """Initialize components after dataclass init."""
        self._classifier = IVRClassifier()
        self._loop_detector = LoopDetector(
            similarity_threshold=self.config.loop_similarity_threshold,
            max_history=self.config.max_transcript_history,
        )
        self._dtmf_parser = DTMFParser(self.config.dtmf_tag_pattern)
        self._status = IVRStatus()
        self.logger = logger.bind(service="ivr_detector")

    @property
    def status(self) -> IVRStatus:
        """Get current IVR detection status."""
        return self._status

    @property
    def mode(self) -> IVRMode:
        """Get current operating mode."""
        return self._status.mode

    async def process_transcript(
        self,
        transcript: str,
        is_agent: bool = False,
    ) -> IVRMode:
        """Process a transcript and update IVR detection state.

        Args:
            transcript: Speech transcript to process
            is_agent: True if this is agent speech, False for user/remote party

        Returns:
            Current IVR mode after processing
        """
        if not transcript or len(transcript.strip()) < self.config.min_transcript_length:
            return self._status.mode

        # For agent transcripts, check DTMF AND add to loop detection
        if is_agent:
            self._check_dtmf_tags(transcript)

            # Track agent DTMF for loop detection
            if self._status.mode == IVRMode.IVR and self._status.last_dtmf_sent:
                synthetic = f"Pressed {self._status.last_dtmf_sent}"
                self._loop_detector.add_transcript(synthetic)

                if self._loop_detector.is_loop_detected():
                    self._status.loop_detected = True
                    self.logger.warning("agent_dtmf_loop_detected")

            return self._status.mode

        # For remote party transcripts, classify and detect loops
        mode, confidence = self._classifier.classify(transcript)

        # Detect context from transcript
        detected_context = self._classifier.detect_context(transcript)
        if detected_context != DTMFContext.UNKNOWN:
            self._status.menu_state.context = detected_context
            self.logger.info("ivr_context_detected", context=detected_context.value)

        self.logger.info(
            "ivr_transcript_classified",
            mode=mode.value,
            confidence=confidence,
            transcript_preview=transcript[:100],
        )

        # Update consecutive counts based on classification
        self._update_counts(mode)

        # Check if we should switch modes
        self._check_mode_switch()

        # If in IVR mode, check for loops
        if self._status.mode == IVRMode.IVR:
            self._loop_detector.add_transcript(transcript)
            if self._loop_detector.is_loop_detected():
                self._status.loop_detected = True
                if self.on_loop_detected:
                    self.on_loop_detected()

        return self._status.mode

    def _update_counts(self, classified_mode: IVRMode) -> None:
        """Update consecutive classification counts.

        Args:
            classified_mode: Mode from current classification
        """
        if classified_mode in {IVRMode.IVR, IVRMode.VOICEMAIL}:
            self._status.consecutive_ivr_count += 1
            self._status.consecutive_human_count = 0
        elif classified_mode == IVRMode.CONVERSATION:
            self._status.consecutive_human_count += 1
            self._status.consecutive_ivr_count = 0
        # UNKNOWN doesn't reset counts - maintains momentum

    def _check_mode_switch(self) -> None:
        """Check if mode should switch based on consecutive counts."""
        old_mode = self._status.mode
        new_mode = old_mode

        threshold = self.config.consecutive_classifications

        if self._status.consecutive_ivr_count >= threshold:
            new_mode = IVRMode.IVR
        elif self._status.consecutive_human_count >= threshold:
            new_mode = IVRMode.CONVERSATION
            # Reset loop detection when switching to conversation
            self._loop_detector.reset()
            self._status.loop_detected = False

        if new_mode != old_mode:
            self.logger.info(
                "ivr_mode_change",
                old_mode=old_mode.value,
                new_mode=new_mode.value,
                consecutive_ivr=self._status.consecutive_ivr_count,
                consecutive_human=self._status.consecutive_human_count,
            )
            self._status.mode = new_mode
            if self.on_mode_change:
                self.on_mode_change(old_mode, new_mode)

    def _check_dtmf_tags(self, text: str) -> None:
        """Check agent response for DTMF tags and track digits.

        NOTE: This method only TRACKS DTMF digits for loop detection purposes.
        It does NOT send DTMF. The DTMFHandler.check_and_send() is the single
        source of truth for sending DTMF to prevent duplication bugs.

        Args:
            text: Agent response text
        """
        digits_list = self._dtmf_parser.parse(text)

        for digits in digits_list:
            # Track the digit for loop detection - but do NOT invoke callback
            # The DTMFHandler is responsible for actually sending DTMF
            self._status.last_dtmf_sent = digits

    def strip_dtmf_tags(self, text: str) -> str:
        """Strip DTMF tags from text.

        Args:
            text: Text that may contain DTMF tags

        Returns:
            Text with tags removed
        """
        return self._dtmf_parser.strip_dtmf_tags(text)

    def record_dtmf_attempt(self, digits: str) -> None:
        """Record a DTMF attempt.

        Args:
            digits: The DTMF digits that were sent
        """
        self._status.attempted_dtmf.add(digits)
        self._status.last_dtmf_sent = digits
        # Also record in menu_state
        if self._status.menu_state:
            self._status.menu_state.attempted_dtmf.add(digits)
        self.logger.debug(
            "dtmf_attempt_recorded",
            digits=digits,
            total_attempted=len(self._status.attempted_dtmf),
        )

    def record_dtmf_failed(self, digits: str) -> None:
        """Record that a DTMF didn't change the menu.

        Args:
            digits: The DTMF digits that failed to produce a change
        """
        self._status.failed_dtmf.add(digits)
        self.logger.info(
            "dtmf_marked_as_failed",
            digits=digits,
            total_failed=len(self._status.failed_dtmf),
        )

    def get_untried_digits(self) -> list[str]:
        """Get menu digits (1-9) not yet attempted.

        Returns:
            Sorted list of digits that haven't been tried yet
        """
        all_digits = set("123456789")
        return sorted(all_digits - self._status.attempted_dtmf)

    def should_skip_digit(self, digits: str) -> bool:
        """Check if digit already failed.

        Args:
            digits: The DTMF digits to check

        Returns:
            True if the digits have already been tried and failed
        """
        return digits in self._status.failed_dtmf

    def validate_menu_changed(self, new_transcript: str) -> bool:
        """Check if menu changed after DTMF.

        Compares the new transcript with the last menu transcript to determine
        if the DTMF press actually navigated to a different menu.

        Args:
            new_transcript: The new transcript from the IVR

        Returns:
            True if menu is different (DTMF worked), False if same (DTMF failed)
        """
        if not self._status.last_menu_transcript:
            self._status.last_menu_transcript = new_transcript
            return True

        similarity = self._loop_detector._calculate_similarity(
            self._status.last_menu_transcript,
            new_transcript,
        )

        menu_changed = similarity < self.config.loop_similarity_threshold

        # If menu didn't change and we sent DTMF, mark it as failed
        if not menu_changed and self._status.last_dtmf_sent:
            self.record_dtmf_failed(self._status.last_dtmf_sent)
            self.logger.warning(
                "dtmf_did_not_change_menu",
                digits=self._status.last_dtmf_sent,
                similarity=similarity,
                threshold=self.config.loop_similarity_threshold,
            )

        # Update last menu transcript
        self._status.last_menu_transcript = new_transcript
        return menu_changed

    def reset(self) -> None:
        """Reset all detection state."""
        self._status = IVRStatus()
        self._loop_detector.reset()
        self.logger.info("ivr_detector_reset")

    def get_ivr_navigation_prompt(self, goal: str | None = None) -> str:
        """Get IVR navigation prompt for the current state.

        Args:
            goal: Optional navigation goal (e.g., "reach sales department")

        Returns:
            Prompt string for IVR navigation
        """
        parts = []

        parts.append(
            "You are navigating an automated phone menu (IVR). "
            "Listen carefully to ALL options before responding."
        )

        # Critical timing instructions
        parts.append(
            "\nIMPORTANT TIMING RULES:"
            "\n- Wait for the COMPLETE menu to finish speaking before responding"
            "\n- Don't respond mid-menu - let the IVR system finish all options"
            "\n- Wait 2-3 seconds of silence after the menu stops before sending DTMF"
            "\n- Only send ONE digit at a time, then wait for the system's response"
        )

        if goal:
            parts.append(f"\nYour goal: {goal}")

        # Add info about tried digits
        if self._status.attempted_dtmf:
            tried = ", ".join(sorted(self._status.attempted_dtmf))
            parts.append(f"\nDigits already tried: {tried}")

        if self._status.failed_dtmf:
            failed = ", ".join(sorted(self._status.failed_dtmf))
            parts.append(f"Digits that didn't work: {failed}")

        untried = self.get_untried_digits()
        if untried and self._status.attempted_dtmf:
            parts.append(f"Try one of these next: {', '.join(untried[:3])}")

        if self._status.loop_detected:
            parts.append(
                "\nWARNING: The menu is repeating. Try a DIFFERENT numbered option (1-9) "
                "that you haven't tried yet. Only use '0' or '#' as a last resort."
            )

        parts.append(
            "\nTo select an option, include the digit in <dtmf>X</dtmf> tags. "
            "Example: <dtmf>1</dtmf> to press 1. Send ONLY ONE digit per response."
        )

        return "\n".join(parts)
