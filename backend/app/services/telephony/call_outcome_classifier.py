"""Call outcome classifier for determining call status from hangup causes."""

from dataclasses import dataclass

from app.models.conversation import MessageStatus


@dataclass
class CallClassificationResult:
    """Result of classifying a call outcome.

    Attributes:
        outcome: Call outcome (no_answer, busy, rejected, voicemail, completed, None)
        message_status: Message status to set (failed, completed)
        is_rejection: Whether this was detected as a rejection
        error_code: Telnyx hangup cause code for failed calls
        error_message: Human-readable error message for failed calls
    """

    outcome: str | None
    message_status: MessageStatus
    is_rejection: bool = False
    error_code: str | None = None
    error_message: str | None = None


class CallOutcomeClassifier:
    """Classifies call outcomes based on hangup cause and call metadata.

    Maps Telnyx hangup causes to semantic outcomes for campaign tracking
    and SMS fallback triggering.
    """

    # Human-readable messages for hangup causes
    HANGUP_CAUSE_MESSAGES: dict[str, str] = {
        "NO_ANSWER": "Call was not answered",
        "TIMEOUT": "Call timed out waiting for answer",
        "ORIGINATOR_CANCEL": "Call was canceled before answer",
        "USER_BUSY": "Recipient line was busy",
        "CALL_REJECTED": "Call was rejected by recipient",
    }

    # Calls under this threshold with NORMAL_CLEARING are treated as failed
    # (0s = no connection, 1-4s = quick reject/no conversation)
    # 5+ seconds = real interaction happened, no SMS fallback needed
    SHORT_CALL_THRESHOLD_SECS = 5

    # Hangup causes that indicate no answer
    NO_ANSWER_CAUSES = frozenset({"NO_ANSWER", "TIMEOUT", "ORIGINATOR_CANCEL"})

    # Hangup causes that indicate user is busy
    BUSY_CAUSES = frozenset({"USER_BUSY"})

    # Hangup causes that indicate explicit rejection
    REJECTION_CAUSES = frozenset({"CALL_REJECTED"})

    # Normal clearing causes (need additional context to classify)
    NORMAL_CLEARING_CAUSES = frozenset({"NORMAL_CLEARING", "NORMAL_RELEASE"})

    def classify(  # noqa: PLR0912
        self,
        hangup_cause: str,
        duration_secs: int,
        hangup_source: str,
        booking_outcome: str | None = None,
    ) -> CallClassificationResult:
        """Classify a call outcome based on hangup cause and call metadata.

        Args:
            hangup_cause: Telnyx hangup cause (e.g., NO_ANSWER, USER_BUSY)
            duration_secs: Call duration in seconds
            hangup_source: Who hung up (e.g., "callee", "caller")
            booking_outcome: Optional booking outcome (e.g., "success")

        Returns:
            CallClassificationResult with outcome, message_status, and is_rejection
        """
        # Normalize hangup cause to uppercase
        hangup_cause = hangup_cause.upper() if hangup_cause else ""

        # Determine call outcome based on hangup cause
        call_outcome: str | None = None
        message_status: MessageStatus = MessageStatus.COMPLETED  # Default to completed
        is_rejected_call = False

        if hangup_cause in self.NO_ANSWER_CAUSES:
            call_outcome = "no_answer"
            message_status = MessageStatus.FAILED
        elif hangup_cause in self.BUSY_CAUSES:
            call_outcome = "busy"
            message_status = MessageStatus.FAILED
        elif hangup_cause in self.REJECTION_CAUSES:
            call_outcome = "rejected"
            message_status = MessageStatus.FAILED
            is_rejected_call = True
        elif hangup_cause in self.NORMAL_CLEARING_CAUSES:
            if duration_secs == 0:
                # No connection made
                call_outcome = "no_answer"
                message_status = MessageStatus.FAILED
            elif duration_secs < self.SHORT_CALL_THRESHOLD_SECS and hangup_source == "callee":
                # Callee hung up almost immediately — quick auto-reject
                call_outcome = "rejected"
                message_status = MessageStatus.FAILED
                is_rejected_call = True
            elif duration_secs < self.SHORT_CALL_THRESHOLD_SECS:
                # Caller or other hung up very quickly — no real conversation
                call_outcome = "no_answer"
                message_status = MessageStatus.FAILED
            # 5+ seconds with NORMAL_CLEARING = real interaction, leave as completed

        # If booking was successful, override failed status
        if booking_outcome == "success" and message_status == MessageStatus.FAILED:
            message_status = MessageStatus.COMPLETED

        # Populate error fields for failed calls
        error_code: str | None = None
        error_message: str | None = None
        if message_status == MessageStatus.FAILED and hangup_cause:
            error_code = hangup_cause
            if call_outcome == "rejected":
                error_message = "Call rejected (hung up quickly)"
            elif call_outcome == "no_answer" and duration_secs == 0:
                error_message = "Call not connected"
            elif call_outcome == "no_answer":
                error_message = "Call ended too quickly for conversation"
            else:
                error_message = self.HANGUP_CAUSE_MESSAGES.get(
                    hangup_cause, f"Call failed: {hangup_cause}"
                )

        return CallClassificationResult(
            outcome=call_outcome,
            message_status=message_status,
            is_rejection=is_rejected_call,
            error_code=error_code,
            error_message=error_message,
        )

    def classify_machine_detection(self, result_type: str) -> str | None:
        """Classify machine detection result.

        Args:
            result_type: Detection result (human, machine, fax, silence)

        Returns:
            Call outcome if machine/fax detected, None otherwise
        """
        if result_type in ("machine", "fax"):
            return "voicemail"
        return None
