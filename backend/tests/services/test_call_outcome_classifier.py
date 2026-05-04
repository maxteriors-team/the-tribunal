"""Tests for app.services.telephony.call_outcome_classifier."""

import pytest

from app.services.telephony.call_outcome_classifier import (
    CallClassificationResult,
    CallOutcomeClassifier,
)


@pytest.fixture
def classifier() -> CallOutcomeClassifier:
    """Provide a fresh classifier instance."""
    return CallOutcomeClassifier()


class TestCallClassificationResultDataclass:
    """Tests for the CallClassificationResult dataclass."""

    def test_default_values(self) -> None:
        """Default values for optional fields."""
        result = CallClassificationResult(outcome=None, message_status="completed")
        assert result.outcome is None
        assert result.message_status == "completed"
        assert result.is_rejection is False
        assert result.error_code is None
        assert result.error_message is None

    def test_full_construction(self) -> None:
        """All fields can be set via constructor."""
        result = CallClassificationResult(
            outcome="rejected",
            message_status="failed",
            is_rejection=True,
            error_code="CALL_REJECTED",
            error_message="Call rejected (hung up quickly)",
        )
        assert result.outcome == "rejected"
        assert result.message_status == "failed"
        assert result.is_rejection is True
        assert result.error_code == "CALL_REJECTED"
        assert result.error_message == "Call rejected (hung up quickly)"


class TestClassifyNoAnswerCauses:
    """NO_ANSWER_CAUSES → no_answer outcome."""

    @pytest.mark.parametrize("cause", ["NO_ANSWER", "TIMEOUT", "ORIGINATOR_CANCEL"])
    def test_no_answer_causes(
        self, classifier: CallOutcomeClassifier, cause: str
    ) -> None:
        """Each NO_ANSWER cause classifies to no_answer + failed."""
        result = classifier.classify(
            hangup_cause=cause, duration_secs=0, hangup_source="caller"
        )
        assert result.outcome == "no_answer"
        assert result.message_status == "failed"
        assert result.is_rejection is False
        assert result.error_code == cause
        # error_message pulled from HANGUP_CAUSE_MESSAGES when duration != 0 path;
        # but duration=0 sets "Call not connected"
        assert result.error_message == "Call not connected"

    def test_no_answer_nonzero_duration_uses_mapped_message(
        self, classifier: CallOutcomeClassifier
    ) -> None:
        """NO_ANSWER with nonzero duration uses the HANGUP_CAUSE_MESSAGES map."""
        # With NO_ANSWER as hangup_cause, duration is irrelevant to outcome
        # but affects error_message branch.
        result = classifier.classify(
            hangup_cause="NO_ANSWER", duration_secs=3, hangup_source="caller"
        )
        assert result.outcome == "no_answer"
        # duration_secs != 0 branch hits the "ended too quickly" message
        assert result.error_message == "Call ended too quickly for conversation"


class TestClassifyBusyCauses:
    """BUSY_CAUSES → busy outcome."""

    def test_user_busy(self, classifier: CallOutcomeClassifier) -> None:
        """USER_BUSY classifies to busy + failed."""
        result = classifier.classify(
            hangup_cause="USER_BUSY", duration_secs=0, hangup_source="caller"
        )
        assert result.outcome == "busy"
        assert result.message_status == "failed"
        assert result.is_rejection is False
        assert result.error_code == "USER_BUSY"
        assert result.error_message == "Recipient line was busy"


class TestClassifyRejectionCauses:
    """REJECTION_CAUSES → rejected outcome."""

    def test_call_rejected(self, classifier: CallOutcomeClassifier) -> None:
        """CALL_REJECTED classifies to rejected + failed + is_rejection True."""
        result = classifier.classify(
            hangup_cause="CALL_REJECTED", duration_secs=0, hangup_source="callee"
        )
        assert result.outcome == "rejected"
        assert result.message_status == "failed"
        assert result.is_rejection is True
        assert result.error_code == "CALL_REJECTED"
        assert result.error_message == "Call rejected (hung up quickly)"


class TestClassifyNormalClearing:
    """NORMAL_CLEARING_CAUSES with various durations."""

    @pytest.mark.parametrize("cause", ["NORMAL_CLEARING", "NORMAL_RELEASE"])
    def test_zero_duration_is_no_answer(
        self, classifier: CallOutcomeClassifier, cause: str
    ) -> None:
        """NORMAL_CLEARING with 0 duration = no_answer + failed."""
        result = classifier.classify(
            hangup_cause=cause, duration_secs=0, hangup_source="caller"
        )
        assert result.outcome == "no_answer"
        assert result.message_status == "failed"
        assert result.error_code == cause
        assert result.error_message == "Call not connected"

    def test_short_duration_callee_hangup_is_rejected(
        self, classifier: CallOutcomeClassifier
    ) -> None:
        """Short call with callee hanging up = rejected."""
        result = classifier.classify(
            hangup_cause="NORMAL_CLEARING", duration_secs=2, hangup_source="callee"
        )
        assert result.outcome == "rejected"
        assert result.message_status == "failed"
        assert result.is_rejection is True
        assert result.error_message == "Call rejected (hung up quickly)"

    def test_short_duration_caller_hangup_is_no_answer(
        self, classifier: CallOutcomeClassifier
    ) -> None:
        """Short call with caller hanging up = no_answer."""
        result = classifier.classify(
            hangup_cause="NORMAL_CLEARING", duration_secs=3, hangup_source="caller"
        )
        assert result.outcome == "no_answer"
        assert result.message_status == "failed"
        assert result.is_rejection is False
        assert result.error_message == "Call ended too quickly for conversation"

    def test_short_duration_other_source_is_no_answer(
        self, classifier: CallOutcomeClassifier
    ) -> None:
        """Short call with non-callee source is no_answer."""
        result = classifier.classify(
            hangup_cause="NORMAL_CLEARING", duration_secs=1, hangup_source="unknown"
        )
        assert result.outcome == "no_answer"

    def test_long_duration_is_completed(
        self, classifier: CallOutcomeClassifier
    ) -> None:
        """5+ seconds with NORMAL_CLEARING leaves as completed with no outcome."""
        result = classifier.classify(
            hangup_cause="NORMAL_CLEARING", duration_secs=5, hangup_source="callee"
        )
        assert result.outcome is None
        assert result.message_status == "completed"
        assert result.is_rejection is False
        assert result.error_code is None
        assert result.error_message is None

    def test_very_long_duration_is_completed(
        self, classifier: CallOutcomeClassifier
    ) -> None:
        """Long call is completed."""
        result = classifier.classify(
            hangup_cause="NORMAL_CLEARING", duration_secs=120, hangup_source="caller"
        )
        assert result.outcome is None
        assert result.message_status == "completed"


class TestClassifyBookingOverride:
    """booking_outcome='success' overrides failed status."""

    def test_booking_success_overrides_failed(
        self, classifier: CallOutcomeClassifier
    ) -> None:
        """Booking success upgrades failed to completed."""
        result = classifier.classify(
            hangup_cause="NO_ANSWER",
            duration_secs=0,
            hangup_source="caller",
            booking_outcome="success",
        )
        # Outcome remains no_answer but status is upgraded
        assert result.outcome == "no_answer"
        assert result.message_status == "completed"
        # When status is completed, error fields are not populated
        assert result.error_code is None
        assert result.error_message is None

    def test_booking_non_success_does_not_override(
        self, classifier: CallOutcomeClassifier
    ) -> None:
        """Non-success booking outcome does not upgrade status."""
        result = classifier.classify(
            hangup_cause="USER_BUSY",
            duration_secs=0,
            hangup_source="caller",
            booking_outcome="failed",
        )
        assert result.message_status == "failed"
        assert result.error_code == "USER_BUSY"

    def test_booking_success_on_already_completed(
        self, classifier: CallOutcomeClassifier
    ) -> None:
        """Booking success on already completed call stays completed."""
        result = classifier.classify(
            hangup_cause="NORMAL_CLEARING",
            duration_secs=60,
            hangup_source="caller",
            booking_outcome="success",
        )
        assert result.message_status == "completed"


class TestClassifyNormalization:
    """Uppercase normalization of hangup_cause."""

    def test_lowercase_hangup_cause(self, classifier: CallOutcomeClassifier) -> None:
        """Lowercase hangup cause is normalized."""
        result = classifier.classify(
            hangup_cause="no_answer", duration_secs=0, hangup_source="caller"
        )
        assert result.outcome == "no_answer"
        # error_code stored in normalized uppercase
        assert result.error_code == "NO_ANSWER"

    def test_mixed_case_hangup_cause(self, classifier: CallOutcomeClassifier) -> None:
        """Mixed-case hangup cause is normalized."""
        result = classifier.classify(
            hangup_cause="User_Busy", duration_secs=0, hangup_source="caller"
        )
        assert result.outcome == "busy"
        assert result.error_code == "USER_BUSY"

    def test_empty_hangup_cause(self, classifier: CallOutcomeClassifier) -> None:
        """Empty hangup cause leaves outcome None, status completed."""
        result = classifier.classify(
            hangup_cause="", duration_secs=0, hangup_source="caller"
        )
        assert result.outcome is None
        assert result.message_status == "completed"
        assert result.error_code is None
        assert result.error_message is None

    def test_unknown_hangup_cause_stays_completed(
        self, classifier: CallOutcomeClassifier
    ) -> None:
        """Unknown hangup cause defaults to completed with no outcome."""
        result = classifier.classify(
            hangup_cause="SOMETHING_WEIRD", duration_secs=10, hangup_source="caller"
        )
        assert result.outcome is None
        assert result.message_status == "completed"
        assert result.error_code is None


class TestClassifyErrorFields:
    """Error code and error message population for each outcome."""

    def test_error_message_fallback_for_unknown_failed(
        self, classifier: CallOutcomeClassifier
    ) -> None:
        """Unknown hangup cause that somehow fails uses generic fallback."""
        # The "else" branch inside the error_message block only fires when
        # call_outcome is something other than rejected/no_answer, e.g. busy.
        result = classifier.classify(
            hangup_cause="USER_BUSY", duration_secs=0, hangup_source="caller"
        )
        # busy uses HANGUP_CAUSE_MESSAGES entry
        assert result.error_message == "Recipient line was busy"

    def test_timeout_message(self, classifier: CallOutcomeClassifier) -> None:
        """TIMEOUT with 0 duration uses 'Call not connected'."""
        result = classifier.classify(
            hangup_cause="TIMEOUT", duration_secs=0, hangup_source="caller"
        )
        assert result.error_code == "TIMEOUT"
        assert result.error_message == "Call not connected"


class TestClassifyMachineDetection:
    """Tests for classify_machine_detection."""

    def test_machine_is_voicemail(self, classifier: CallOutcomeClassifier) -> None:
        """'machine' returns 'voicemail'."""
        assert classifier.classify_machine_detection("machine") == "voicemail"

    def test_fax_is_voicemail(self, classifier: CallOutcomeClassifier) -> None:
        """'fax' returns 'voicemail'."""
        assert classifier.classify_machine_detection("fax") == "voicemail"

    def test_human_returns_none(self, classifier: CallOutcomeClassifier) -> None:
        """'human' returns None."""
        assert classifier.classify_machine_detection("human") is None

    def test_silence_returns_none(self, classifier: CallOutcomeClassifier) -> None:
        """'silence' returns None."""
        assert classifier.classify_machine_detection("silence") is None

    def test_unknown_returns_none(self, classifier: CallOutcomeClassifier) -> None:
        """Unknown result_type returns None."""
        assert classifier.classify_machine_detection("not_detected") is None

    def test_empty_returns_none(self, classifier: CallOutcomeClassifier) -> None:
        """Empty string returns None."""
        assert classifier.classify_machine_detection("") is None
