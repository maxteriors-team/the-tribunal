"""Tests for IVRClassifier edge cases.

These tests verify the critical fix for IVR vs voicemail misclassification.
The key bug was that "Press 1 to leave a message" was classified as voicemail
because voicemail patterns would win ties.

The fix ensures that:
1. If ANY exclusive IVR pattern (DTMF prompt) is present → always IVR
2. Voicemail is only returned when there are NO IVR patterns
"""

from app.services.ai.ivr_detector import IVRClassifier, IVRMode


class TestIVRClassifierBasics:
    """Basic classification tests."""

    def test_empty_transcript_returns_unknown(self, ivr_classifier: IVRClassifier):
        """Empty or very short transcripts should return UNKNOWN."""
        mode, confidence = ivr_classifier.classify("")
        assert mode == IVRMode.UNKNOWN
        assert confidence == 0.0

        mode, confidence = ivr_classifier.classify("hi")
        assert mode == IVRMode.UNKNOWN
        assert confidence == 0.0

    def test_whitespace_transcript_returns_unknown(self, ivr_classifier: IVRClassifier):
        """Whitespace-only transcripts should return UNKNOWN."""
        mode, confidence = ivr_classifier.classify("   ")
        assert mode == IVRMode.UNKNOWN
        assert confidence == 0.0


class TestIVRClassifierVoicemailEdgeCases:
    """Critical edge case tests for IVR vs voicemail classification."""

    def test_press_1_to_leave_message_is_ivr(self, ivr_classifier: IVRClassifier):
        """CRITICAL: 'Press 1 to leave a message' should be IVR, not voicemail.

        This was the original bug - voicemail patterns matched and won.
        """
        transcript = "Press 1 to leave a message. Press 2 for sales."

        mode, confidence = ivr_classifier.classify(transcript)

        assert mode == IVRMode.IVR, (
            f"Expected IVR for '{transcript}' but got {mode.value}. "
            "DTMF prompts should ALWAYS classify as IVR."
        )
        assert confidence > 0.5

    def test_press_option_with_voicemail_mention(self, ivr_classifier: IVRClassifier):
        """IVR menu that mentions voicemail as option should be IVR."""
        transcript = "Press 1 to leave a voicemail. Press 2 for sales. Press 0 for an operator."

        mode, confidence = ivr_classifier.classify(transcript)

        assert mode == IVRMode.IVR

    def test_press_to_leave_callback(self, ivr_classifier: IVRClassifier):
        """'Press X to leave a callback' should be IVR."""
        transcript = "Press 1 to leave a callback number."

        mode, confidence = ivr_classifier.classify(transcript)

        assert mode == IVRMode.IVR

    def test_pure_voicemail_no_dtmf(self, ivr_classifier: IVRClassifier):
        """Pure voicemail greeting with NO DTMF prompts should be VOICEMAIL."""
        transcript = (
            "Hi, you've reached John Smith. "
            "I'm not available to take your call. "
            "Please leave your name and number after the beep, "
            "and I'll get back to you as soon as possible."
        )

        mode, confidence = ivr_classifier.classify(transcript)

        assert mode == IVRMode.VOICEMAIL, (
            f"Expected VOICEMAIL for '{transcript[:50]}...' but got {mode.value}. "
            "Pure voicemail with no DTMF should classify as VOICEMAIL."
        )

    def test_voicemail_at_the_beep_no_dtmf(self, ivr_classifier: IVRClassifier):
        """'Leave a message at the beep' without DTMF should be VOICEMAIL."""
        transcript = "Please leave a message at the beep."

        mode, confidence = ivr_classifier.classify(transcript)

        assert mode == IVRMode.VOICEMAIL

    def test_voicemail_after_the_tone(self, ivr_classifier: IVRClassifier):
        """'After the tone' without DTMF should be VOICEMAIL."""
        transcript = "Record your message after the tone."

        mode, confidence = ivr_classifier.classify(transcript)

        assert mode == IVRMode.VOICEMAIL


class TestIVRClassifierStandardIVR:
    """Tests for standard IVR menu patterns."""

    def test_press_for_sales_support(self, ivr_classifier: IVRClassifier):
        """Standard 'Press 1 for X, Press 2 for Y' should be IVR."""
        transcript = "Press 1 for sales. Press 2 for support."

        mode, confidence = ivr_classifier.classify(transcript)

        assert mode == IVRMode.IVR
        assert confidence > 0.5

    def test_dial_for_operator(self, ivr_classifier: IVRClassifier):
        """'Dial 0 for operator' should be IVR."""
        transcript = "Dial 0 for an operator, or dial 9 for the directory."

        mode, confidence = ivr_classifier.classify(transcript)

        assert mode == IVRMode.IVR

    def test_option_number_pattern(self, ivr_classifier: IVRClassifier):
        """'Option 1 is...' pattern should be IVR."""
        transcript = "Option 1 is for billing. Option 2 is for technical support."

        mode, confidence = ivr_classifier.classify(transcript)

        assert mode == IVRMode.IVR

    def test_say_or_press(self, ivr_classifier: IVRClassifier):
        """'Say or press' pattern should be IVR."""
        transcript = "Say or press 1 for sales. Say or press 2 for support."

        mode, confidence = ivr_classifier.classify(transcript)

        assert mode == IVRMode.IVR

    def test_enter_your_account(self, ivr_classifier: IVRClassifier):
        """'Enter your account number' should be IVR."""
        transcript = "Please enter your account number followed by the pound sign."

        mode, confidence = ivr_classifier.classify(transcript)

        assert mode == IVRMode.IVR

    def test_menu_with_hold_message(self, ivr_classifier: IVRClassifier):
        """IVR with hold message should be IVR."""
        transcript = (
            "Your call is important to us. "
            "Press 1 for sales, press 2 for support. "
            "Please hold for the next available representative."
        )

        mode, confidence = ivr_classifier.classify(transcript)

        assert mode == IVRMode.IVR


class TestIVRClassifierHumanConversation:
    """Tests for human conversation patterns."""

    def test_human_speaking_pattern(self, ivr_classifier: IVRClassifier):
        """'This is X speaking' should be CONVERSATION."""
        transcript = "Hi, this is John speaking. How can I help you today?"

        mode, confidence = ivr_classifier.classify(transcript)

        assert mode == IVRMode.CONVERSATION

    def test_human_greeting_pattern(self, ivr_classifier: IVRClassifier):
        """Human greeting patterns should be CONVERSATION."""
        transcript = "Good morning! How may I help you?"

        mode, confidence = ivr_classifier.classify(transcript)

        assert mode == IVRMode.CONVERSATION

    def test_human_helpfulness(self, ivr_classifier: IVRClassifier):
        """Helpful human responses should be CONVERSATION."""
        transcript = "Let me check that for you. One moment please."

        mode, confidence = ivr_classifier.classify(transcript)

        assert mode == IVRMode.CONVERSATION

    def test_human_acknowledgment(self, ivr_classifier: IVRClassifier):
        """Human acknowledgment patterns should be CONVERSATION."""
        transcript = "Absolutely, I can help you with that. No problem at all."

        mode, confidence = ivr_classifier.classify(transcript)

        assert mode == IVRMode.CONVERSATION


class TestIVRClassifierConfidence:
    """Tests for confidence score accuracy."""

    def test_strong_ivr_patterns_high_confidence(self, ivr_classifier: IVRClassifier):
        """Multiple strong IVR patterns should give high confidence."""
        transcript = (
            "Welcome to Acme Corp. "
            "Press 1 for sales. "
            "Press 2 for support. "
            "Press 3 for billing. "
            "Press 0 for an operator."
        )

        mode, confidence = ivr_classifier.classify(transcript)

        assert mode == IVRMode.IVR
        assert confidence >= 0.6, f"Expected confidence >= 0.6, got {confidence}"

    def test_strong_voicemail_patterns_high_confidence(self, ivr_classifier: IVRClassifier):
        """Strong voicemail patterns should give high confidence."""
        transcript = (
            "You've reached the voicemail of Jane Doe. "
            "Please leave your message after the beep. "
            "I'll get back to you as soon as possible."
        )

        mode, confidence = ivr_classifier.classify(transcript)

        assert mode == IVRMode.VOICEMAIL
        assert confidence >= 0.5


class TestIVRClassifierEdgeCasesComplex:
    """Complex edge case tests."""

    def test_multiple_conflicting_patterns(self, ivr_classifier: IVRClassifier):
        """When IVR patterns are present with voicemail words, IVR wins."""
        transcript = (
            "To leave a message, press 1. "
            "To speak with an agent, press 2. "
            "Your message will be recorded after the beep if you press 1."
        )

        mode, confidence = ivr_classifier.classify(transcript)

        # DTMF prompts should make this IVR
        assert mode == IVRMode.IVR

    def test_voicemail_box_full_no_dtmf(self, ivr_classifier: IVRClassifier):
        """'Mailbox is full' without DTMF should be VOICEMAIL."""
        transcript = "The mailbox is full. Please try again later."

        mode, confidence = ivr_classifier.classify(transcript)

        assert mode == IVRMode.VOICEMAIL

    def test_call_queue_with_dtmf(self, ivr_classifier: IVRClassifier):
        """Call queue with DTMF options should be IVR."""
        transcript = (
            "All of our representatives are currently assisting other customers. "
            "Press 1 to continue waiting. "
            "Press 2 to leave a callback number."
        )

        mode, confidence = ivr_classifier.classify(transcript)

        assert mode == IVRMode.IVR
